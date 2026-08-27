import json
import math
import os
import re
import shutil
import pandas as pd

from services.migration_service import _build_base_template


def compute_codestation(survey: dict, obs: dict) -> str:
    """Code station : codeObs si déjà calculé, sinon reconstruit depuis zone + 2 derniers
    chiffres de l'année + n° du point. Partagé entre la carte de campagne (qualif_controller)
    et le planificateur de déploiement (comparaison avec les points d'une campagne)."""
    code = (obs.get("codeObs") or {}).get("value")
    if code:
        return str(code)
    zone_v = str((survey.get("zone") or {}).get("value") or "").strip()
    date_v = str((survey.get("date") or {}).get("value") or "").strip()
    year_2d = re.sub(r"[^0-9]", "", date_v)[2:4] if date_v else ""
    pname = str((obs.get("point_name") or {}).get("value")
                or (obs.get("station_number") or {}).get("value") or "").strip()
    if not pname:
        return ""
    try:
        station_idx = f"{int(pname):04d}"
    except ValueError:
        station_idx = pname.zfill(4)[:4]
    return f"{zone_v}{year_2d}{station_idx}" if zone_v and year_2d else ""


def find_campaign_gps_points(campaign_folder: str) -> list:
    """Scanne un dossier de campagne (récursivement) à la recherche de tous les _temp.json
    et retourne leurs points GPS au format attendu par la carte Leaflet du planificateur
    de déploiement (lat/lng/code/nom/date) — utilisé par "Comparer avec campagne"."""
    points = []
    if not campaign_folder or not os.path.isdir(campaign_folder):
        return points
    for root, _dirs, files in os.walk(campaign_folder):
        for fname in files:
            if not fname.endswith("_temp.json"):
                continue
            jpath = os.path.join(root, fname)
            try:
                with open(jpath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                survey = data.get("survey", {})
                obs = data.get("video_observation", {})
                lat = (obs.get("latitude") or {}).get("value")
                lon = (obs.get("longitude") or {}).get("value")
                if lat in (None, "") or lon in (None, ""):
                    continue
                lat_f = float(str(lat).replace(",", "."))
                lon_f = float(str(lon).replace(",", "."))
                if math.isnan(lat_f) or math.isnan(lon_f):
                    continue
                nom = str((obs.get("point_name") or {}).get("value")
                          or (obs.get("station_number") or {}).get("value") or "").strip()
                date_v = str((survey.get("date") or {}).get("value") or "").strip()
                points.append({
                    "lat": lat_f, "lng": lon_f,
                    "code": compute_codestation(survey, obs),
                    "nom": nom, "date": date_v,
                })
            except (ValueError, TypeError, OSError, json.JSONDecodeError):
                continue
    return points


def get_video_gps_coords(video_path: str) -> tuple:
    """Extrait les coordonnées GPS d'une vidéo.

    Source prioritaire : _temp.json (video_observation.latitude/longitude) — la copie de
    travail IHM, modifiable/corrigeable via la page Métadonnées (import GPX, saisie
    manuelle...). Repli sur le CSV de télémétrie brute uniquement si le _temp.json n'a
    rien d'exploitable, pour ne jamais perdre une position déjà disponible.

    Args:
        video_path: Chemin vers le fichier MP4.

    Returns:
        Tuple (latitude, longitude) ou None si absent/corrompu.
    """
    temp_json_path = get_temp_json_path(video_path)
    if os.path.isfile(temp_json_path):
        try:
            with open(temp_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            obs = data.get("video_observation", {})
            lat = (obs.get("latitude") or {}).get("value")
            lon = (obs.get("longitude") or {}).get("value")
            if lat not in (None, "") and lon not in (None, ""):
                lat_f = float(str(lat).replace(",", "."))
                lon_f = float(str(lon).replace(",", "."))
                if not (math.isnan(lat_f) or math.isnan(lon_f)):
                    return lat_f, lon_f
        except Exception as e:
            print(f"Erreur lecture GPS depuis _temp.json : {e}")

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

    for root, _, __ in os.walk(campaign_folder):
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

    Format cible : YYYYMMDDhhmm_ZONE_CODESTATION  (ex: 202207181314_ATL_CC220006)
    - YYYYMMDDhhmm = survey.date + heure extraite du stem (ou video_observation.time)
    - ZONE         = survey.zone.value
    - CODESTATION  = survey.zone.value + année 2 chiffres + index station 4 chiffres

    Fallback sur le stem du fichier vidéo si le JSON est absent ou incomplet.
    """
    stem = os.path.splitext(os.path.basename(video_path))[0]

    # Extraire HHmm depuis le stem (formats : YYYYMMDDhhmm_... ou YYYYMMDDHHmmss_...)
    hhmm = ""
    m_stem = re.match(r'^\d{8}(\d{4,6})', stem)
    if m_stem:
        hhmm = m_stem.group(1)[:4]

    # _temp.json = données IHM à jour (zone/date/point saisis dans l'app) ; le JSON
    # brut d'acquisition n'est jamais mis à jour par l'IHM et serait donc périmé ici.
    json_path = get_temp_json_path(video_path)
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

    # Si pas de temps dans le stem, essayer video_observation.time
    if not hhmm:
        obs_time = (data.get("video_observation", {}).get("time", {}).get("value") or "").strip()
        if obs_time:
            hhmm = obs_time.replace(":", "").replace("h", "")[:4]

    year_2d = date[2:4] if len(date) >= 4 else "00"

    # N° du point saisi à l'ardoise (point_name en priorité, station_number en repli)
    vo = data.get("video_observation", {})
    station_num_raw = ((vo.get("point_name", {}).get("value"))
                        or (vo.get("station_number", {}).get("value")) or "").strip()
    if station_num_raw:
        try:
            station_idx = f"{int(station_num_raw):04d}"
        except ValueError:
            station_idx = station_num_raw.zfill(4)[:4]
    else:
        # Fallback anciens projets : dossier parent numérique
        parent_name = os.path.basename(os.path.dirname(os.path.normpath(video_path)))
        try:
            station_idx = f"{int(parent_name):04d}"
        except ValueError:
            m = re.search(r'(\d{4})$', parent_name)
            station_idx = m.group(1) if m else "0000"

    codestation = f"{zone}{year_2d}{station_idx}"
    date_hhmm = f"{date}{hhmm}" if hhmm else date
    return f"{date_hhmm}_{region}_{codestation}"


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
    """Copie uniquement le JSON source dans son sous-dossier de travail.

    Le JSON n'est jamais écrasé s'il existe déjà (il contient les annotations).
    Lors de la première copie, video_file_name est mis à jour avec le nom standardisé.
    """
    import json as _json
    import subprocess as _sp
    src_dir = os.path.dirname(os.path.normpath(video_path))
    dst_dir = get_working_video_dir(working_dir, video_path)
    os.makedirs(dst_dir, exist_ok=True)

    # Rendre .kosmos_work invisible dans l'explorateur Windows
    work_root = os.path.join(working_dir, _WORK_SUBDIR)
    if os.path.isdir(work_root):
        try:
            _sp.run(["attrib", "+h", work_root], shell=True, capture_output=True)
        except Exception:
            pass
    stem = os.path.splitext(os.path.basename(video_path))[0]
    json_fname = f"{stem}.json"
    src_file = os.path.join(src_dir, json_fname)
    if not os.path.isfile(src_file):
        return
    dst_file = os.path.join(dst_dir, json_fname)
    if os.path.exists(dst_file):
        return
    shutil.copy2(src_file, dst_file)
    try:
        with open(dst_file, 'r', encoding='utf-8') as f:
            data = _json.load(f)
        vo = data.setdefault('video_observation', {})
        # Standardiser le nom de fichier vidéo
        vfn = vo.get('video_file_name', {})
        if isinstance(vfn, dict):
            ext = os.path.splitext(video_path)[1]
            vfn['value'] = build_video_output_name(video_path) + ext
        # Forcer exploitable à "?" à la première copie — la source peut avoir "oui" par défaut
        expl = vo.setdefault('exploitable', {})
        if expl.get('value') == 'oui':
            expl['value'] = '?'
        with open(dst_file, 'w', encoding='utf-8') as f:
            _json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def get_temp_json_path(video_path: str) -> str:
    """Retourne le chemin du fichier <stem>_temp.json dans le dossier de la vidéo brute."""
    folder = os.path.dirname(os.path.normpath(video_path))
    stem = os.path.splitext(os.path.basename(video_path))[0]
    return os.path.join(folder, f"{stem}_temp.json")


def get_working_video_json_path(working_dir: str, video_path: str) -> str:
    """Redirige vers get_temp_json_path (ancien système working_dir remplacé par _temp.json)."""
    return get_temp_json_path(video_path)


def resolve_video_json_path(working_dir: str, video_path: str) -> str:
    """Retourne le chemin JSON IHM actif : <stem>_temp.json dans le dossier brut."""
    return get_temp_json_path(video_path)


_WORK_SUBDIR = ".kosmos_work"


def get_working_video_dir(working_dir: str, video_path: str) -> str:
    """Retourne le sous-dossier vidéo dans le répertoire de travail interne.

    Les JSONs de travail sont stockés dans <working_dir>/.kosmos_work/<stem>/
    pour ne pas polluer BenthOS_sorties avec les anciens noms.
    Compatibilité : cherche d'abord dans .kosmos_work/, puis à la racine (anciens projets).
    """
    stem = os.path.splitext(os.path.basename(video_path))[0]
    json_fname = f"{stem}.json"
    work_root = os.path.join(working_dir, _WORK_SUBDIR)

    # Priorité 1 : dossier dans .kosmos_work/ (nouveau format)
    if os.path.isdir(work_root):
        for folder in os.listdir(work_root):
            folder_path = os.path.join(work_root, folder)
            if os.path.isdir(folder_path) and os.path.isfile(os.path.join(folder_path, json_fname)):
                return folder_path

    # Priorité 2 : compat anciens projets — dossier à la racine du working_dir
    if os.path.isdir(working_dir):
        for folder in os.listdir(working_dir):
            if folder == _WORK_SUBDIR:
                continue
            folder_path = os.path.join(working_dir, folder)
            if os.path.isdir(folder_path) and os.path.isfile(os.path.join(folder_path, json_fname)):
                return folder_path

    # Nouveau dossier → dans .kosmos_work/
    return os.path.join(work_root, stem)


def get_infostation_path(working_dir: str) -> str:
    """Retourne le chemin du CSV Infostation global dans le répertoire de travail.

    Le nom est basé sur le nom du répertoire (ex: '2026' → 'infostation_2026.csv').
    """
    year_label = os.path.basename(os.path.normpath(working_dir))
    return os.path.join(working_dir, f"infostation_{year_label}.csv")


def get_campaign_output_dir(campaign_folder: str) -> str:
    """Retourne le dossier de sortie IHM pour une campagne (BenthOS_sorties)."""
    return os.path.join(os.path.dirname(os.path.normpath(campaign_folder)), "BenthOS_sorties")


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
