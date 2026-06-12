import os
import cv2

from services.campaign_service import extract_date_from_template


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
        if "trash" in root.split(os.sep):
            continue

        current_folder_date = extract_date_from_template(root)

        for file in files:
            if file.lower().endswith(".mp4"):
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
    """Vérifie si le dossier d'une vidéo contient exactement deux fichiers MP4 (stéréo).

    Args:
        video_path: Chemin vers l'un des fichiers MP4.

    Returns:
        Tuple (is_stereo: bool, video_payload: str|list).
        En mode stéréo, video_payload est une liste [path_L, path_R] triée.
    """
    if not video_path:
        return False, None

    video_dir = os.path.dirname(video_path)
    if not os.path.exists(video_dir):
        return False, video_path

    all_videos = [
        os.path.join(video_dir, f)
        for f in os.listdir(video_dir)
        if f.lower().endswith(".mp4")
    ]

    if len(all_videos) == 2:
        all_videos.sort()
        return True, all_videos

    return False, video_path
