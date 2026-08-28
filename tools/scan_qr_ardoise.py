"""
Script annexe (diagnostic) : scanne une vidéo à la recherche du QR code présent
sur l'ardoise (coin en haut à gauche de la plaquette bleue) et affiche ce qu'il
décode, avec le timecode correspondant.

N'écrit rien dans les fichiers de campagne (_temp.json) : c'est un outil de test
pour vérifier si/comment le QR code est lisible, avant d'envisager une intégration
dans l'IHM (auto-remplissage du numéro de point par ex.).

Usage :
    python tools/scan_qr_ardoise.py "chemin/vers/0164.mp4"
    python tools/scan_qr_ardoise.py "0164.mp4" --start 00:02:30 --end 00:03:30
    python tools/scan_qr_ardoise.py "0164.mp4" --step 2 --enhance --save-dir out_qr
"""
import argparse
import os
import sys
import time

import cv2

# Évite les caractères accentués mangés dans la console Windows (cp1252/cp850 par défaut).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")


def parse_time(s: str) -> float:
    """Accepte 'HH:MM:SS', 'MM:SS' ou un nombre de secondes brut."""
    s = s.strip()
    if ":" not in s:
        return float(s)
    parts = [float(p) for p in s.split(":")]
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds


def format_timecode(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:05.2f}"


def enhance_frame(frame):
    """Niveaux de gris + CLAHE : aide la détection si l'ardoise est peu contrastée
    (reflets, faible luminosité en profondeur)."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    return clahe.apply(gray)


def detect_qr(detector, image):
    """Essaie detectAndDecodeMulti puis, en repli, detectAndDecode (single)."""
    try:
        ok_multi, decoded_infos, _points, _straight = detector.detectAndDecodeMulti(image)
        if ok_multi:
            non_empty = [d for d in decoded_infos if d]
            if non_empty:
                return " | ".join(non_empty)
    except cv2.error:
        pass
    try:
        single, _points, _straight = detector.detectAndDecode(image)
        if single:
            return single
    except cv2.error:
        pass
    return None


def scan_video(video_path, step, start_sec, end_sec, save_dir, use_enhance):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Impossible d'ouvrir la vidéo : {video_path}", file=sys.stderr)
        return 1

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps if fps else 0.0

    start_frame = int((start_sec or 0.0) * fps)
    end_frame = int((end_sec if end_sec is not None else duration) * fps)
    end_frame = max(start_frame + 1, min(end_frame, frame_count))

    if save_dir:
        os.makedirs(save_dir, exist_ok=True)

    detector = cv2.QRCodeDetector()
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    print(f"Vidéo         : {video_path}")
    print(f"Durée totale  : {format_timecode(duration)}  ({frame_count} frames @ {fps:.2f} fps)")
    print(f"Plage scannée : {format_timecode(start_frame / fps)} -> {format_timecode(end_frame / fps)}")
    print(f"Pas           : 1 frame sur {step}" + ("  (+ enhance)" if use_enhance else ""))
    print("-" * 60)

    last_value = None
    detections = []  # (timecode_sec, value)
    frame_idx = start_frame
    t0 = time.time()
    next_progress = start_frame + max(step, (end_frame - start_frame) // 10 or 1)

    while frame_idx < end_frame:
        if not cap.grab():
            break

        if (frame_idx - start_frame) % step == 0:
            ok, frame = cap.retrieve()
            if ok:
                image = enhance_frame(frame) if use_enhance else frame
                value = detect_qr(detector, image)
                timecode_sec = frame_idx / fps

                if value and value != last_value:
                    tc = format_timecode(timecode_sec)
                    print(f"[{tc}] QR détecté : {value!r}")
                    detections.append((timecode_sec, value))
                    if save_dir:
                        fname = os.path.join(save_dir, f"qr_{tc.replace(':', '-')}.png")
                        cv2.imwrite(fname, frame)
                elif value is None and last_value is not None:
                    print(f"[{format_timecode(timecode_sec)}] (QR perdu)")

                last_value = value

        if frame_idx >= next_progress:
            elapsed = time.time() - t0
            pct = 100 * (frame_idx - start_frame) / max(1, end_frame - start_frame)
            print(f"...{pct:4.0f}%  ({format_timecode(frame_idx / fps)})  [{elapsed:.0f}s écoulées]",
                  file=sys.stderr)
            next_progress += max(step, (end_frame - start_frame) // 10 or 1)

        frame_idx += 1

    cap.release()

    print("-" * 60)
    if detections:
        print(f"{len(detections)} détection(s) unique(s) :")
        for tc_sec, value in detections:
            print(f"  {format_timecode(tc_sec)}  ->  {value!r}")
    else:
        print("Aucun QR code détecté sur la plage scannée.")
        print("Pistes : ardoise hors champ sur cette plage, angle/flou/reflet,")
        print("essayer --enhance, réduire --step (risque de sauter la frame nette),")
        print("ou vérifier --start/--end via le marker 'Ardoise' de la timeline Validation.")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Scanne une vidéo à la recherche d'un QR code (ardoise) et affiche son "
                    "contenu décodé avec le timecode. Diagnostic uniquement : n'écrit rien "
                    "dans les JSON de campagne.")
    parser.add_argument("video", help="Chemin vers le fichier vidéo (.mp4)")
    parser.add_argument("--start", default=None,
                         help="Début de la plage à scanner (HH:MM:SS, MM:SS ou secondes)")
    parser.add_argument("--end", default=None,
                         help="Fin de la plage à scanner (HH:MM:SS, MM:SS ou secondes)")
    parser.add_argument("--step", type=int, default=5,
                         help="N'analyse qu'une frame sur N (défaut : 5)")
    parser.add_argument("--enhance", action="store_true",
                         help="Niveaux de gris + CLAHE avant détection (aide si l'ardoise est peu contrastée)")
    parser.add_argument("--save-dir", default=None,
                         help="Si fourni, enregistre une image PNG à chaque nouvelle détection")
    args = parser.parse_args()

    if not os.path.isfile(args.video):
        print(f"Fichier introuvable : {args.video}", file=sys.stderr)
        return 1

    start_sec = parse_time(args.start) if args.start else None
    end_sec = parse_time(args.end) if args.end else None

    return scan_video(args.video, max(1, args.step), start_sec, end_sec, args.save_dir, args.enhance)


if __name__ == "__main__":
    sys.exit(main())
