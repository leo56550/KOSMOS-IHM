import pandas as pd
from datetime import datetime


def get_motor_stable_timestamps(csv_path: str, delay: float = 6.0, start_track_id: int = 6) -> list:
    """Calcule les timestamps stables depuis un fichier systemEvent.csv.

    Extrait les démarrages moteur, calcule les offsets temporels depuis l'encodeur
    de référence, déduit les angles de rotation et retourne des données structurées
    pour la visualisation sur la timeline.

    Args:
        csv_path: Chemin vers le fichier CSV systemEvent.
        delay: Offset temporel en secondes à ajouter à chaque événement (défaut 6.0).
        start_track_id: Identifiant de départ pour la séquence de tracks (défaut 6).

    Returns:
        Liste de dicts avec 'track_id', 'timestamp', 'duration', 'start' (ms),
        'type', 'angle', 'rotation_index'.
    """
    try:
        df = pd.read_csv(csv_path, sep=None, engine='python', encoding='utf-8')
    except Exception:
        df = pd.read_csv(csv_path, sep=None, engine='python', encoding='cp1252')

    df.columns = [c.strip().lower() for c in df.columns]

    col_event = 'event'
    col_time = 'heure'

    if col_event not in df.columns:
        raise KeyError(f"Colonne 'Event' introuvable. Colonnes détectées : {list(df.columns)}")

    df[col_event] = df[col_event].astype(str).str.strip().str.upper()
    df[col_time] = df[col_time].astype(str).str.strip()

    start_encoder_rows = df[df[col_event] == 'START ENCODER']
    if start_encoder_rows.empty:
        print("START ENCODER non trouvé, utilisation de la première ligne.")
        t0_str = df.iloc[0][col_time]
    else:
        t0_str = start_encoder_rows.iloc[0][col_time]

    t0 = datetime.strptime(t0_str, "%Hh%Mm%Ss")

    motor_rows = df[df[col_event] == 'START MOTEUR']

    structural_events = []
    track_id = start_track_id

    for i, (_, row) in enumerate(motor_rows.iterrows()):
        t_event_str = row[col_time]
        try:
            t_event = datetime.strptime(t_event_str, "%Hh%Mm%Ss")
            delta = (t_event - t0).total_seconds() + delay
            if delta >= 0:
                angle_step = (i % 6) + 1
                calculated_angle = angle_step * 60

                if calculated_angle == 360:
                    rotation_type = "rotation_360°"
                else:
                    rotation_type = f"rotation_{calculated_angle}°"

                delta_ms = int(delta * 1000)

                structural_events.append({
                    "track_id": track_id,
                    "timestamp": delta,
                    "duration": 6.0,
                    "start": delta_ms,
                    "type": rotation_type,
                    "angle": calculated_angle,
                    "rotation_index": (i // 6) + 1
                })
                track_id += 1

        except Exception as e:
            print(f"Erreur de format temporel : {e}")

    return structural_events
