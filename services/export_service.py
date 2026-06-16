import os
import cv2
import pandas as pd
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from services.synchro_service import get_rectification_maps, get_synced_indices


class ExportWorker(QThread):
    """Worker asynchrone pour l'exportation à 5 FPS avec traitements optionnels (HE, dehaze, rectification)."""

    progress_updated = pyqtSignal(int)
    export_finished = pyqtSignal(int)
    export_error = pyqtSignal(str)

    def __init__(self, video_path: str, base_output_dir: str, start_ms: int, end_ms: int,
                 target_fps: float, events: list, apply_he: bool = False,
                 apply_dh: bool = False, is_water: bool = False,
                 is_stereo: bool = False, apply_rectify: bool = False, json_path: str = None):
        """
        Args:
            video_path: Chemin de la vidéo source (flux R en stéréo).
            base_output_dir: Dossier racine d'export (img/LEFT et img/RIGHT y seront créés).
            start_ms, end_ms: Fenêtre temporelle d'export en millisecondes.
            target_fps: Cadence cible pour l'échantillonnage des frames.
            events: Liste d'événements (non utilisée dans le run actuel, réservé).
            apply_he: Active l'égalisation d'histogramme.
            apply_dh: Active le débrumage CLAHE.
            is_water: Mode sous-marin (ajustements de canaux avant CLAHE).
            is_stereo: Exporte les deux flux L et R.
            apply_rectify: Applique la rectification stéréo via matrices.json.
            json_path: Chemin vers le fichier de calibration stéréo (matrices.json).
        """
        super().__init__()
        self.video_path = video_path
        self.base_output_dir = base_output_dir
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.target_fps = target_fps
        self.events = events if events else []
        self.apply_he = apply_he
        self.apply_dh = apply_dh
        self.is_water = is_water
        self.is_stereo = is_stereo
        self.apply_rectify = apply_rectify
        self.json_path = json_path
        self.maps_L = None
        self.maps_R = None

    def run(self):
        """Extrait les frames dans img/LEFT (et img/RIGHT en stéréo), émet progress_updated puis export_finished."""
        try:
            print(f"\n--- DÉBUT DE L'EXPORT ---")
            print(f"Mode Stéréo: {self.is_stereo} | Rectification: {self.apply_rectify}")

            img_dir = os.path.normpath(os.path.join(self.base_output_dir, "img"))
            dirs = {"L": os.path.join(img_dir, "LEFT")}
            if self.is_stereo:
                dirs["R"] = os.path.join(img_dir, "RIGHT")

            for key, d in dirs.items():
                os.makedirs(d, exist_ok=True)
                count_removed = 0
                for f in os.listdir(d):
                    if f.endswith(".jpg"):
                        os.remove(os.path.join(d, f))
                        count_removed += 1
                print(f"[DOSSIER] Nettoyage {key}: {count_removed} images supprimées.")

            if self.is_stereo and self.apply_rectify:
                if not self.json_path or not os.path.exists(self.json_path):
                    self.export_error.emit("Fichier matrices.json introuvable.")
                    return
                self.maps_L, self.maps_R = get_rectification_maps(self.json_path)

            video_R_path = self.video_path
            video_L_path = self.video_path.replace(".mp4", "_stereo.mp4")

            capR = cv2.VideoCapture(video_R_path)
            capL = cv2.VideoCapture(video_L_path) if self.is_stereo else None

            fps = capR.get(cv2.CAP_PROP_FPS)
            if fps <= 0:
                fps = 25.0

            if self.is_stereo:
                txt_L = video_L_path.replace(".mp4", ".txt")
                txt_R = video_R_path.replace(".mp4", ".txt")
                all_matches = get_synced_indices(txt_L, txt_R, self.target_fps, fps)
                tL = pd.read_csv(txt_L, header=None).iloc[:, 0].values
                matches = [m for m in all_matches if self.start_ms <= tL[m[0]] <= self.end_ms]
            else:
                interval = max(1, int(fps / self.target_fps))
                start_f = int((self.start_ms / 1000.0) * fps)
                end_f = int((self.end_ms / 1000.0) * fps)
                matches = [(None, i) for i in range(start_f, end_f, interval)]

            if len(matches) == 0:
                self.export_finished.emit(0)
                return

            total_extracted = 0
            total_to_do = len(matches)

            for k, (idxL, idxR) in enumerate(matches):
                if idxR is not None:
                    capR.set(cv2.CAP_PROP_POS_FRAMES, idxR)
                    retR, frameR = capR.read()
                    if retR:
                        if self.apply_rectify and self.maps_R:
                            frameR = cv2.remap(frameR, self.maps_R[0], self.maps_R[1], cv2.INTER_LINEAR)
                        if self.apply_he or self.apply_dh:
                            frameR = self._apply_image_filters(frameR)
                        save_path = os.path.join(dirs.get("R", dirs["L"]), f"{k+1:05d}.jpg")
                        cv2.imwrite(save_path, frameR)

                if self.is_stereo and idxL is not None:
                    capL.set(cv2.CAP_PROP_POS_FRAMES, idxL)
                    retL, frameL = capL.read()
                    if retL:
                        if self.apply_rectify and self.maps_L:
                            frameL = cv2.remap(frameL, self.maps_L[0], self.maps_L[1], cv2.INTER_LINEAR)
                        if self.apply_he or self.apply_dh:
                            frameL = self._apply_image_filters(frameL)
                        cv2.imwrite(os.path.join(dirs["L"], f"{k+1:05d}.jpg"), frameL)

                total_extracted += 1
                self.progress_updated.emit(int(((k + 1) / total_to_do) * 100))

            capR.release()
            if capL:
                capL.release()

            print(f"--- EXPORT RÉUSSI : {total_extracted} images ---\n")
            self.export_finished.emit(total_extracted)

        except Exception as e:
            print(f"\n[ERREUR CRITIQUE] {str(e)}")
            self.export_error.emit(f"Erreur Export : {str(e)}")

    def _apply_image_filters(self, frame: np.ndarray) -> np.ndarray:
        """Applique HE et/ou dehaze sur une frame BGR selon les options de l'instance."""
        processed = frame.copy()
        try:
            if self.apply_he:
                hsv = cv2.cvtColor(processed, cv2.COLOR_BGR2HSV)
                hsv[:, :, 2] = cv2.equalizeHist(hsv[:, :, 2])
                processed = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
            if self.apply_dh:
                processed = self._dehaze_image(processed)
        except Exception as e:
            print(f"Erreur filtre image : {e}")
        return processed

    def _dehaze_image(self, img: np.ndarray, strength: float = 1.0) -> np.ndarray:
        """Débrume via CLAHE sur le canal L (LAB), avec ajustement de canaux en mode sous-marin."""
        try:
            img_float = img.astype(np.float32) / 255.0
            if self.is_water:
                img_float[:, :, 0] *= 0.7
                img_float[:, :, 1] *= 1.2
                img_float[:, :, 2] *= 1.15
            clahe = cv2.createCLAHE(clipLimit=strength * 2.0, tileGridSize=(8, 8))
            img_lab = cv2.cvtColor(
                (np.clip(img_float, 0, 1) * 255).astype(np.uint8),
                cv2.COLOR_BGR2LAB
            )
            img_lab[:, :, 0] = clahe.apply(img_lab[:, :, 0])
            return cv2.cvtColor(img_lab, cv2.COLOR_LAB2BGR)
        except Exception:
            return img


class VideoSegmentationWorker(QThread):
    """Worker thread pour exporter une portion de vidéo (découpe temporelle)."""

    progress_updated = pyqtSignal(int)
    export_finished = pyqtSignal(str)
    export_error = pyqtSignal(str)

    def __init__(self, video_path: str, start_ms: int, end_ms: int, output_dir: str):
        """
        Args:
            video_path: Chemin de la vidéo source.
            start_ms, end_ms: Fenêtre temporelle à découper en millisecondes.
            output_dir: Dossier de destination du segment MP4.
        """
        super().__init__()
        self.video_path = video_path
        self.start_ms = max(0, start_ms)
        self.end_ms = end_ms
        self.output_dir = output_dir

    def run(self):
        """Découpe la vidéo entre start_ms et end_ms et écrit le résultat dans output_dir."""
        try:
            cap = cv2.VideoCapture(self.video_path)
            if not cap.isOpened():
                self.export_error.emit(f"Impossible d'ouvrir la vidéo : {self.video_path}")
                return

            fps = cap.get(cv2.CAP_PROP_FPS)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            if fps == 0:
                self.export_error.emit("Impossible de récupérer les propriétés vidéo (FPS=0)")
                cap.release()
                return

            start_frame = int((self.start_ms / 1000.0) * fps)
            end_frame = min(int((self.end_ms / 1000.0) * fps), total_frames - 1)

            if start_frame >= end_frame:
                self.export_error.emit("Frame de début >= Frame de fin")
                cap.release()
                return

            os.makedirs(self.output_dir, exist_ok=True)

            base_name = os.path.splitext(os.path.basename(self.video_path))[0]
            output_path = os.path.join(
                self.output_dir,
                f"{base_name}_segment_{self.start_ms}_{self.end_ms}.mp4"
            )

            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

            if not out.isOpened():
                self.export_error.emit(f"Impossible de créer le fichier : {output_path}")
                cap.release()
                return

            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

            frame_count = 0
            total_frames_to_export = end_frame - start_frame + 1

            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                current_frame = int(cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
                if current_frame > end_frame:
                    break
                if current_frame >= start_frame:
                    out.write(frame)
                    frame_count += 1
                    progress = int((frame_count / total_frames_to_export) * 100)
                    self.progress_updated.emit(progress)

            cap.release()
            out.release()

            file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
            msg = (f"Vidéo exportée avec succès !\n\n"
                   f"{output_path}\n{frame_count} frames\n{file_size_mb:.2f} MB")
            self.export_finished.emit(msg)

        except Exception as e:
            self.export_error.emit(f"Erreur lors de l'export : {str(e)}")
