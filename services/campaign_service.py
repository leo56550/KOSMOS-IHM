import json
import os
import re
import shutil
import pandas as pd

from services.migration_service import _build_base_template


def get_video_gps_coords(video_path: str) -> tuple:
    """Extrait les coordonnées GPS depuis le CSV compagnon d'une vidéo.

    Args:
        video_path: Chemin vers le fichier MP4.

    Returns:
        Tuple (latitude, longitude) ou None si absent/corrompu.
    """
    gps_csv_path = video_path.replace(".mp4", ".csv")
    if os.path.exists(gps_csv_path):
        try:
            df = pd.read_csv(gps_csv_path, sep=None, engine='python')
            df.columns = [c.strip().lower() for c in df.columns]

            if 'lat' in df.columns and 'long' in df.columns:
                latitude = float(df['lat'].iloc[0])
                longitude = float(df['long'].iloc[0])
                return latitude, longitude
            else:
                print(f"Colonnes GPS manquantes dans : {gps_csv_path}. Trouvé : {list(df.columns)}")
        except Exception as e:
            print(f"Erreur lecture GPS : {e}")
    return None


def get_video_json_path(video_path: str) -> str:
    """Return the JSON path for a given video: same folder, same stem, .json extension.

    After campaign opening, the IHM only interacts with <stem>.json.
    template.json is the source used to initialise <stem>.json on first open.
    """
    folder = os.path.dirname(os.path.normpath(video_path))
    stem = os.path.splitext(os.path.basename(video_path))[0]
    return os.path.join(folder, f"{stem}.json")


def _find_first_json_in_folder(folder: str) -> str | None:
    """Return the first non-backup, non-template .json file found in *folder*, or None.

    template.json is the seed file; once the IHM initialises the video-named JSON
    it becomes stale — always prefer the video-named copy.
    """
    try:
        candidates = sorted(
            fname for fname in os.listdir(folder)
            if fname.endswith(".json")
            and fname != "template.json"
            and not fname.endswith(".legacy_backup")
        )
        if candidates:
            return os.path.join(folder, candidates[0])
        # Fallback: no video-named JSON yet → accept template.json
        if os.path.isfile(os.path.join(folder, "template.json")):
            return os.path.join(folder, "template.json")
    except OSError:
        pass
    return None


def get_campaign_json_data(campaign_folder: str, extract_system: bool = False) -> dict:
    """Parcourt la structure du dossier campagne pour trouver le premier JSON vidéo.

    Args:
        campaign_folder: Dossier racine de la campagne.
        extract_system: Si True, retourne uniquement le bloc 'system'.

    Returns:
        Dict des données JSON, ou None si introuvable.
    """
    if not campaign_folder or not os.path.exists(campaign_folder):
        return None

    for root, dirs, files in os.walk(campaign_folder):
        if "trash" in root.split(os.sep):
            continue

        json_path = _find_first_json_in_folder(root)
        if json_path is None:
            continue

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                complete_data = json.load(f)

            if extract_system:
                if "system" in complete_data:
                    return complete_data["system"]
                else:
                    print(f"[WARNING] Pas de bloc 'system' dans : {json_path}")
                    return None

            return complete_data

        except Exception as e:
            print(f"[ERROR] Lecture JSON impossible ({json_path}) : {e}")

    print("[WARNING] Aucun JSON vidéo trouvé dans le dossier campagne.")
    return None


def build_video_output_name(video_path: str) -> str:
    """Construit le nom de sortie d'une vidéo depuis ses métadonnées JSON.

    Format cible : YYYYMMDD_REGION_CODESTATION  (ex: 20260618_LLL_IF260042)
    - YYYYMMDD   = survey.date.value
    - REGION     = survey.region.value
    - CODESTATION = survey.zone.value + année 2 chiffres + index station 4 chiffres
      (l'index station = nom numérique du dossier parent de la vidéo)

    Fallback sur le stem du fichier vidéo si le JSON est absent ou incomplet.
    """
    stem = os.path.splitext(os.path.basename(video_path))[0]
    json_path = get_video_json_path(video_path)
    if not os.path.isfile(json_path):
        return stem
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return stem

    surv = data.get("survey", {})
    date   = (surv.get("date",   {}).get("value") or "").strip()
    region = (surv.get("region", {}).get("value") or "").strip()
    zone   = (surv.get("zone",   {}).get("value") or "").strip()

    if not (date and region and zone):
        return stem

    year_2d = date[2:4] if len(date) >= 4 else "00"

    # Index station = nom du dossier parent de la vidéo.
    # Cas 1 – nom purement numérique (ex: "0042") → index direct
    # Cas 2 – nom déjà formaté (ex: "20260618_LLL_IF260042") → 4 derniers chiffres
    parent_name = os.path.basename(os.path.dirname(os.path.normpath(video_path)))
    try:
        station_idx = f"{int(parent_name):04d}"
    except ValueError:
        m = re.search(r'(\d{4})$', parent_name)
        station_idx = m.group(1) if m else "0000"

    codestation = f"{zone}{year_2d}{station_idx}"
    return f"{date}_{region}_{codestation}"


def migrate_json_to_template(json_path: str) -> bool:
    """Fusionne les champs manquants du schéma complet dans le JSON vidéo du répertoire de travail.

    Utilise _build_base_template() comme référence (source unique de vérité).
    Seuls les champs absents sont ajoutés avec value=null ; les valeurs existantes sont préservées.
    Les listes d'événements (events_*) déjà présentes ne sont jamais écrasées.
    Retourne True si le fichier a été modifié.
    """
    if not os.path.isfile(json_path):
        return False

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    template = _build_base_template()
    modified = False

    for block_key, block_tmpl in template.items():
        if not isinstance(block_tmpl, dict):
            continue
        block_data = data.setdefault(block_key, {})
        for field_key, field_def in block_tmpl.items():
            if field_key not in block_data:
                block_data[field_key] = field_def if not isinstance(field_def, dict) else dict(field_def)
                modified = True

    if modified:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    return modified


def sync_video_to_working_dir(working_dir: str, video_path: str) -> None:
    """Copie / met à jour les fichiers compagnon d'une vidéo dans son sous-dossier de travail.

    Tous les fichiers du dossier source sont copiés (JSON, CSV GPS, systemEvent…),
    sauf le .mp4 (trop volumineux). Les fichiers existants sont toujours écrasés
    pour que le JSON reste à jour après chaque sauvegarde de métadonnées.
    Les répertoires (img/, captures/…) ne sont jamais touchés.
    """
    import json as _json
    src_dir = os.path.dirname(os.path.normpath(video_path))
    dst_dir = get_working_video_dir(working_dir, video_path)
    os.makedirs(dst_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(video_path))[0]
    for fname in os.listdir(src_dir):
        if fname.lower().endswith('.mp4'):
            continue
        src_file = os.path.join(src_dir, fname)
        if not os.path.isfile(src_file):
            continue
        dst_file = os.path.join(dst_dir, fname)
        shutil.copy2(src_file, dst_file)
        # Après copie du JSON : injecter le nom standardisé dans video_file_name
        if fname.lower().endswith('.json') and fname.lower() != 'template.json':
            try:
                with open(dst_file, 'r', encoding='utf-8') as f:
                    data = _json.load(f)
                vo = data.get('video_observation', {})
                vfn = vo.get('video_file_name', {})
                if isinstance(vfn, dict):
                    ext = os.path.splitext(video_path)[1]
                    vfn['value'] = build_video_output_name(video_path) + ext
                    with open(dst_file, 'w', encoding='utf-8') as f:
                        _json.dump(data, f, indent=2, ensure_ascii=False)
            except Exception:
                pass


def get_working_video_json_path(working_dir: str, video_path: str) -> str:
    """Retourne le chemin du JSON dans le sous-dossier de travail d'une vidéo."""
    stem = os.path.splitext(os.path.basename(video_path))[0]
    return os.path.join(get_working_video_dir(working_dir, video_path), f"{stem}.json")


def resolve_video_json_path(working_dir: str, video_path: str) -> str:
    """Retourne le chemin JSON actif.

    Préfère le JSON du répertoire de travail (modifiable) si disponible.
    Fallback sur le JSON source (lecture seule) sinon.
    """
    if working_dir:
        wp = get_working_video_json_path(working_dir, video_path)
        if os.path.exists(wp):
            return wp
    return get_video_json_path(video_path)


def get_working_video_dir(working_dir: str, video_path: str) -> str:
    """Retourne le sous-dossier vidéo dans le répertoire de travail.

    Le nom du sous-dossier est construit depuis les métadonnées JSON :
    YYYYMMDD_REGION_CODESTATION  (ex: 20260618_LLL_IF260042)
    """
    name = build_video_output_name(video_path)
    return os.path.join(working_dir, name)


def get_infostation_path(working_dir: str) -> str:
    """Retourne le chemin du CSV Infostation global dans le répertoire de travail.

    Le nom est basé sur le nom du répertoire (ex: '2026' → 'infostation_2026.csv').
    """
    year_label = os.path.basename(os.path.normpath(working_dir))
    return os.path.join(working_dir, f"infostation_{year_label}.csv")


def get_campaign_output_dir(campaign_folder: str) -> str:
    """Retourne le dossier de sortie IHM pour une campagne.

    Structure : <campaign_folder>/<campaign_name>_sortie_ihm/
    Ce dossier contiendra tous les fichiers générés par l'IHM :
    images exportées, CSV VIAME, CSV infostation, captures.
    """
    name = os.path.basename(os.path.normpath(campaign_folder))
    return os.path.join(campaign_folder, f"{name}_sortie_ihm")


def get_video_output_dir(campaign_folder: str, video_path: str) -> str:
    """Retourne le sous-dossier de sortie pour une vidéo donnée.

    Structure : <campaign_output_dir>/<video_stem>/
    """
    stem = os.path.splitext(os.path.basename(video_path))[0]
    return os.path.join(get_campaign_output_dir(campaign_folder), stem)


def extract_date_from_template(folder_path: str) -> str:
    """Extrait la date d'enquête depuis le template.json d'un dossier.

    Args:
        folder_path: Dossier contenant un éventuel template.json.

    Returns:
        La valeur de survey.date.value, ou '--' si absente.
    """
    json_path = _find_first_json_in_folder(folder_path)
    if json_path and os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("survey", {}).get("date", {}).get("value", "--")
        except Exception as e:
            print(f"Erreur lecture date JSON : {e}")
    return "--"
