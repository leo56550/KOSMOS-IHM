import os
import re
import cv2

from services.campaign_service import extract_date_from_template


def get_system_name(video_path: str) -> str:
    """Retourne le nom court du système (ex: 'K51') depuis le chemin d'une vidéo.

    Structure attendue : .../campagne/systeme/station/video.mp4
    Le dossier système est le grand-parent du fichier vidéo.
    Le nom court est la partie commençant par 'K' dans le nom du dossier système.
    """
    video_dir   = os.path.dirname(video_path)          # dossier station
    system_dir  = os.path.dirname(video_dir)           # dossier système
    folder_name = os.path.basename(system_dir)         # ex: "260424_SVR_K51"
    for part in folder_name.split("_"):
        if part.upper().startswith("K") and len(part) > 1:
            return part
    return folder_name  # fallback : nom complet si pas de token K


def get_all_mp4_files(parent_folder: str) -> list:
    """Scanne récursivement un dossier campagne et retourne les métadonnées de chaque MP4.

    Ignore les sous-dossiers 'trash'.

    Args:
        parent_folder: Dossier racine de la campagne.

    Returns:
        Liste de dicts triés par nom : 'name', 'path', 'duration', 'fps', 'res', 'size', 'date'.
    """
    video_data = []

    for root, dirs, files in os.walk(parent_folder):
        parts = root.split(os.sep)
        if "segments" in parts:
            continue

        current_folder_date = extract_date_from_template(root)

        for file in files:
            if file.lower().endswith(".mp4") and not file.lower().endswith("_stereo.mp4"):
                full_path = os.path.join(root, file)

                try:
                    bytes_size = os.path.getsize(full_path)
                    size_str = f"{bytes_size / (1024 * 1024):.2f} MB"
                except Exception:
                    size_str = "-- MB"

                cap = cv2.VideoCapture(full_path)
                if cap.isOpened():
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

                    duration_sec = frame_count / fps if fps > 0 else 0
                    duration = f"{int(duration_sec // 60):02d}:{int(duration_sec % 60):02d}"

                    video_data.append({
                        "name": file,
                        "path": full_path,
                        "duration": duration,
                        "fps": f"{fps:.2f}",
                        "res": f"{w}x{h}",
                        "size": size_str,
                        "date": current_folder_date
                    })
                    cap.release()
                else:
                    video_data.append({
                        "name": file,
                        "path": full_path,
                        "duration": "--",
                        "fps": "--",
                        "res": "--",
                        "size": size_str,
                        "date": current_folder_date
                    })

    video_data.sort(key=lambda x: x["name"])
    return video_data


def check_stereo_status(video_path: str):
    """Détecte si un dossier vidéo est en mode stéréo ou segments séquentiels.

    Stéréo   : X.mp4 + X_stereo.mp4  → (True,  [path_main, path_stereo])
    Séquentiel: X.mp4 + X_01.mp4 ...  → (False, path_main)   [_01 ignoré pour l'instant]
    Mono     : un seul .mp4           → (False, video_path)

    Returns:
        Tuple (is_stereo: bool, video_payload: str | list[str])
    """
    import re as _re

    if not video_path:
        return False, None

    video_dir = os.path.dirname(video_path)
    if not os.path.exists(video_dir):
        return False, video_path

    all_videos = sorted(
        os.path.join(video_dir, f)
        for f in os.listdir(video_dir)
        if f.lower().endswith(".mp4")
    )

    if len(all_videos) < 2:
        return False, video_path

    # --- Stéréo : cherche X.mp4 + X_stereo.mp4 parmi tous les .mp4 du dossier ---
    for v in all_videos:
        stem = os.path.splitext(os.path.basename(v))[0]
        if stem.lower().endswith("_stereo"):
            base = stem[:-7]  # retire "_stereo"
            main_candidate = os.path.join(video_dir, base + ".mp4")
            if os.path.exists(main_candidate):
                return True, [main_candidate, v]

    # --- Segments séquentiels : X.mp4 + X_01.mp4 / X_02.mp4 ... → charge uniquement X.mp4 ---
    stems = [os.path.splitext(os.path.basename(v))[0] for v in all_videos]
    primaries = [s for s in stems if not _re.search(r'_\d+$', s)]
    if len(primaries) == 1:
        primary_path = os.path.join(video_dir, primaries[0] + ".mp4")
        if os.path.exists(primary_path):
            return False, primary_path

    # Fallback mono
    return False, video_path


def get_sequential_segments(video_path: str) -> list[str]:
    """Retourne la liste des segments séquentiels liés à video_path (hors lui-même).

    Ex : pour 0066.mp4, retourne ['.../0066_01.mp4', '.../0066_02.mp4', ...]
    Retourne [] si aucun segment trouvé ou si video_path est lui-même un segment (_NN).
    """
    import re as _re

    if not video_path or not os.path.exists(video_path):
        return []

    stem = os.path.splitext(os.path.basename(video_path))[0]
    # Ne pas chercher depuis un fichier _NN lui-même
    if _re.search(r'_\d+$', stem):
        return []

    video_dir = os.path.dirname(video_path)
    pattern = _re.compile(rf'^{_re.escape(stem)}_\d+\.mp4$', _re.IGNORECASE)
    segments = sorted(
        os.path.join(video_dir, f)
        for f in os.listdir(video_dir)
        if pattern.match(f)
    )
    return segments
