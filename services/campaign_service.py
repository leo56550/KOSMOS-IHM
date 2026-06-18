import json
import os
import pandas as pd


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
    """Return the first non-backup .json file path found directly in *folder*, or None."""
    try:
        for fname in sorted(os.listdir(folder)):
            if fname.endswith(".json") and not fname.endswith(".legacy_backup"):
                return os.path.join(folder, fname)
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
