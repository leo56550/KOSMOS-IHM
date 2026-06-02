#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Module utilitaire unifié : Gestion des fichiers de campagne, logs CSV, 
Thread d'exportation (5 FPS) et algorithmes de correction d'images (HE & Dehaze).
"""

import json
import os
import math
from datetime import datetime
import cv2
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from PyQt6.QtCore import QThread, pyqtSignal
# ============================================================================
# EXTRACTION DE TIMESTAMPS ET TRAITEMENT DES LOGS
# ============================================================================

def get_motor_stable_timestamps(csv_path, delay=6.0, start_track_id=6):
    """
    Calcule les timestamps stables à partir du fichier systemEvent.csv.
    Renvoie une liste de dictionnaires contenant les informations pour VIAME.
    """
    try:
        df = pd.read_csv(csv_path, sep=None, engine='python', encoding='utf-8')
    except Exception:
        # Si l'encodage utf-8 échoue, on tente le format Windows
        df = pd.read_csv(csv_path, sep=None, engine='python', encoding='cp1252')
    
    # Nettoyage des colonnes (supprime espaces et mise en minuscule)
    df.columns = [c.strip().lower() for c in df.columns]
    
    col_event = 'event'
    col_heure = 'heure'

    if col_event not in df.columns:
        raise KeyError(f"Colonne 'Event' non trouvée. Colonnes détectées : {list(df.columns)}")

    df[col_event] = df[col_event].astype(str).str.strip().str.upper()
    df[col_heure] = df[col_heure].astype(str).str.strip()

    # Trouver le T0 (START ENCODER)
    start_encoder_rows = df[df[col_event] == 'START ENCODER']
    
    if start_encoder_rows.empty:
        print("START ENCODER non trouvé, tentative sur la première ligne.")
        t0_str = df.iloc[0][col_heure]
    else:
        t0_str = start_encoder_rows.iloc[0][col_heure]

    # Conversion du T0 en objet temps (Format attendu : 11h05m08s)
    t0 = datetime.strptime(t0_str, "%Hh%Mm%Ss")
    
    # Trouver les START MOTEUR
    motor_rows = df[df[col_event] == 'START MOTEUR']
    
    events_structurels = []
    track_id = start_track_id  # Permet d'attribuer un ID unique à chaque rotation (ex: 6, 7, 8...)

    # On ajoute un compteur d'index (i) pour identifier l'angle de rotation
    for i, (_, row) in enumerate(motor_rows.iterrows()):
        t_event_str = row[col_heure]
        try:
            t_event = datetime.strptime(t_event_str, "%Hh%Mm%Ss")
            delta = (t_event - t0).total_seconds() + delay
            if delta >= 0:
                # Calcul de l'angle basé sur l'index (1er=60°, 2e=120°... 6e=360°)
                num_angle = (i % 6) + 1
                calcul_angle = num_angle * 60
                
                # --- IDENTIFICATION DU TYPE ---
                if calcul_angle == 360:
                    type_rotation = "rotation_360°" 
                else:
                    type_rotation = f"rotation_{calcul_angle}°" # Dynamique (rotation_60°, rotation_120°...)
                
                delta_ms = int(delta * 1000)
                
                # On stocke les infos nécessaires pour la timeline en ajoutant la track_id et la durée
                events_structurels.append({
                    "track_id": track_id,          # AJOUT : ID unique pour VIAME
                    "timestamp": delta,
                    "duration": 6.0,               # AJOUT : Durée de la rotation (6 secondes)
                    "start": delta_ms,
                    "type": type_rotation,
                    "angle": calcul_angle,
                    "index_rotation": (i // 6) + 1
                })
                track_id += 1 # On passe à la track suivante (7, puis 8...)
                
        except Exception as e:
            print(f"Erreur format heure : {e}")

    return events_structurels


def extract_frame_at_time(video_path, timestamp_secondes):
    """Extrait une image RGB unique à un timestamp précis en secondes."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Impossible d'ouvrir la vidéo : {video_path}")
        return None

    time_in_ms = int(timestamp_secondes * 1000)
    cap.set(cv2.CAP_PROP_POS_MSEC, time_in_ms)
    success, frame = cap.read()
    cap.release()
    
    if success and frame is not None:
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return frame_rgb
    else:
        print(f"Échec de l'extraction à {timestamp_secondes}s ({time_in_ms}ms)")
        return None


# ============================================================================
# CLASSE THREAD POUR L'EXPORT EN 5 FPS AVEC OPTIMISATIONS D'IMAGES
# ============================================================================

class ExportWorker(QThread):
    progress_updated = pyqtSignal(int)
    export_finished = pyqtSignal(int)
    export_error = pyqtSignal(str)

    def __init__(self, video_path, base_output_dir, start_ms, end_ms, target_fps, events, 
                 apply_he=False, apply_dh=False, is_water=False):
        super().__init__()
        self.video_path = video_path
        self.base_output_dir = base_output_dir
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.target_fps = target_fps
        self.events = events if events else []
        self.apply_he = apply_he           # Égalisation d'histogramme
        self.apply_dh = apply_dh           # Débrumage (Dehaze)
        self.is_water = is_water           # Mode sous-marin
        self.video_fps = 25.0  # Valeur par défaut

    def run(self):
        try:
            # Créer le dossier img/
            img_dir = os.path.normpath(os.path.join(self.base_output_dir, "img"))
            os.makedirs(img_dir, exist_ok=True)
            
            # Nettoyer TOUS les anciens fichiers du dossier img
            for old_file in os.listdir(img_dir):
                try:
                    os.remove(os.path.join(img_dir, old_file))
                except Exception:
                    pass
            
            # Ouvrir la vidéo
            cap = cv2.VideoCapture(self.video_path)
            if not cap.isOpened():
                self.export_error.emit("Impossible d'ouvrir la vidéo source.")
                return

            video_fps = cap.get(cv2.CAP_PROP_FPS)
            if video_fps <= 0:
                video_fps = 25.0
            
            self.video_fps = video_fps

            # Calcul de l'intervalle : exporter 1 frame tous les N frames (pour atteindre target_fps)
            frame_interval = max(1, int(video_fps / self.target_fps))
            ms_per_frame = 1000.0 / video_fps
            
            # Convertir les bornes temporelles en numéros de frame (frame 1 = 0ms)
            start_frame = int((self.start_ms / 1000.0) * video_fps) + 1
            end_frame = int((self.end_ms / 1000.0) * video_fps) + 1
            
            print(f"[EXPORT] Export 5fps: frames {start_frame} à {end_frame} (interval={frame_interval})")
            
            total_frames_extracted = 0
            
            # Positionner à la frame de départ
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame - 1)
            current_frame = start_frame
            
            while current_frame <= end_frame:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # Vérifier si cette frame doit être extraite (tous les frame_interval frames)
                if (current_frame - start_frame) % frame_interval == 0:
                    filename = f"{(total_frames_extracted + 1):05d}.jpg"
                    filepath = os.path.normpath(os.path.join(img_dir, filename))
                    processed_frame = frame.copy()
                    
                    if self.apply_he or self.apply_dh:
                        processed_frame = self._apply_image_filters(processed_frame)
                    
                    if cv2.imwrite(filepath, processed_frame):
                        total_frames_extracted += 1
                        # Progression
                        segment_size = end_frame - start_frame + 1
                        progress = int(((current_frame - start_frame) / max(1, segment_size)) * 100)
                        self.progress_updated.emit(min(100, max(0, progress)))
                        print(f"[EXPORT] Frame {current_frame} extraite → {filename}")
                    else:
                        print(f"[ERREUR] Impossible d'écrire : {filepath}")
                
                current_frame += 1
            
            cap.release()
            print(f"[EXPORT] Export terminé : {total_frames_extracted} images enregistrées")
            self.export_finished.emit(total_frames_extracted)

        except Exception as e:
            self.export_error.emit(f"Erreur : {str(e)}")

    def _apply_image_filters(self, frame):
        """Applique les filtres de traitement d'image (HE et/ou Dehaze)."""
        processed = frame.copy()
        
        try:
            # Égalisation d'histogramme (HE)
            if self.apply_he:
                # Convertir BGR -> HSV pour égaliser seulement la luminance
                hsv = cv2.cvtColor(processed, cv2.COLOR_BGR2HSV).astype(np.float32)
                hsv[:, :, 2] = cv2.equalizeHist(hsv[:, :, 2].astype(np.uint8))
                processed = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
            
            # Débrumage (Dehaze)
            if self.apply_dh:
                processed = self._dehaze_image(processed)
            
        except Exception as e:
            print(f"[FILTRES] Erreur lors du traitement : {e}")
        
        return processed

    def _dehaze_image(self, img, strength=1.0):
        """
        Applique un effet de débrumage (Dehaze) simple basé sur la récupération de contraste.
        strength: facteur d'intensité du débrumage (0.0 à 2.0+)
        """
        try:
            # Convertir en float
            img_float = img.astype(np.float32) / 255.0
            
            # Mode sous-marin : appliquer une correction de couleur (renforcer les rouges/verts)
            if self.is_water:
                # Renforcer les canaux rouge et vert sous l'eau
                img_float[:, :, 0] *= 0.7  # Réduire bleu (absorption en profondeur)
                img_float[:, :, 1] *= 1.2  # Augmenter vert
                img_float[:, :, 2] *= 1.15  # Augmenter rouge
            
            # Récupération de contraste simple
            kernel_size = 31
            clahe = cv2.createCLAHE(clipLimit=strength * 2.0, tileGridSize=(8, 8))
            
            # Traiter chaque canal
            img_lab = cv2.cvtColor((img_float * 255).astype(np.uint8), cv2.COLOR_BGR2LAB)
            img_lab[:, :, 0] = clahe.apply(img_lab[:, :, 0])
            result = cv2.cvtColor(img_lab, cv2.COLOR_LAB2BGR)
            
            return result
            
        except Exception as e:
            print(f"[DEHAZE] Erreur : {e}")
            return img



# ============================================================================
# ALGORITHMES DE TRAITEMENTS ET CORRECTIONS D'IMAGES (ANCIENNEMENT algos_correction)
# ============================================================================

def BGR2Float(src):
    """Conversion d'un nb sur 8 bits (0 - 255) vers un float64 (0.0 - 1.0)"""
    return src.astype('float64') / 255.0

def Float2BGR(I):
    """Conversion d'un float (0.0 - 1.0) vers un entier 8 bits (0 - 255)"""
    return np.clip(I * 255, 0, 255).astype('uint8')

def AnalyseHisto(I):
    """Moyenne (médiane) et écart-type de chaque canal (Optimisé en O(n))"""
    MeanB = np.median(I[:,:,0])
    MeanG = np.median(I[:,:,1])
    MeanR = np.median(I[:,:,2])
    
    # Utilisation de np.std() pour éviter l'ancienne boucle sum(sum()) très lente
    SquareB = np.std(I[:,:,0])
    SquareG = np.std(I[:,:,1])
    SquareR = np.std(I[:,:,2])
    
    return [MeanB, MeanG, MeanR], [SquareB, SquareG, SquareR]

def PlotHistogram(I):
    """Affiche la distribution des intensités des canaux RGB"""
    plt.figure()
    color = ('b', 'g', 'r')
    for i, col in enumerate(color):
        histr = cv2.calcHist([I], [i], None, [256], [0, 256])
        plt.plot(histr, color=col)
        plt.xlim([0, 256])
    plt.legend(color)
    plt.title('Histogramme des canaux RGB')

def process_image_HE(I, vB=2.0, vG=2.0, vR=2.0):
    """Égalisation d'histogramme basée sur la moyenne et la variance"""
    try:
        [[MeanB, MeanG, MeanR], [SquareB, SquareG, SquareR]] = AnalyseHisto(I)
        II = np.zeros(I.shape, dtype=np.float64)
        
        # Sécurisation contre les divisions par zéro si le canal est uniforme
        sqB = max(SquareB, 1e-5)
        sqG = max(SquareG, 1e-5)
        sqR = max(SquareR, 1e-5)
        
        II[:,:,0] = (I[:,:,0] - MeanB + vB * sqB) / (2 * vB * sqB)
        II[:,:,1] = (I[:,:,1] - MeanG + vG * sqG) / (2 * vG * sqG)
        II[:,:,2] = (I[:,:,2] - MeanR + vR * sqR) / (2 * vR * sqR)

        return Float2BGR(II)
    except Exception as e:
        print(f"Erreur lors de l'égalisation d'histogramme: {e}")
        return I

def DarkChannel(im, sz):
    """Détermine le canal sombre standard de l'image (Minimum des 3 canaux + Érosion)""" 
    b, g, r = cv2.split(im)
    dc = cv2.min(cv2.min(r, g), b)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (sz, sz))
    return cv2.erode(dc, kernel)

def DarkChannelWater(im, sz):
    """Détermine le canal sombre adapté au milieu sous-marin (Exclusion du Rouge)""" 
    b, g, r = cv2.split(im)
    dc = cv2.min(g, b)  # En milieu aquatique, le canal rouge est rapidement absorbé
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (sz, sz))
    return cv2.erode(dc, kernel)

def AtmLight(im, dark):
    """Estimation de la lumière de fond de la scène (A) sur les 0.1% pixels les plus denses""" 
    [h, w] = im.shape[:2]
    imsz = h * w
    numpx = int(max(math.floor(imsz / 1000), 1))
    darkvec = dark.reshape(imsz)
    imvec = im.reshape(imsz, 3)
    indices = darkvec.argsort()
    indices = indices[imsz - numpx:]
    
    # Calcul direct vectorisé de la moyenne
    A = np.mean(imvec[indices], axis=0).reshape(1, 3)
    return A

def TransmissionEstimate(im, A, sz, is_water=False):
    """Estime la carte de transmission en protégeant contre la brume/voile"""
    omega = 0.6
    # SÉCURITÉ : Empêche la division par zéro rencontrée sur les images sombres / pauvres en rouge
    A_safe = np.where(A == 0, 1e-5, A)
    im3 = im / A_safe
    
    if is_water:
        dark_img3 = DarkChannelWater(im3, sz)
    else:
        dark_img3 = DarkChannel(im3, sz)
        
    transmission = 1.0 - omega * dark_img3
    return transmission

def Guidedfilter(im, p, r, eps):
    """Filtre guidé pour affiner les contours de la carte de transmission (évite les halos)"""
    mean_I = cv2.boxFilter(im, cv2.CV_64F, (r, r))
    mean_p = cv2.boxFilter(p, cv2.CV_64F, (r, r))
    mean_Ip = cv2.boxFilter(im * p, cv2.CV_64F, (r, r))
    cov_Ip = mean_Ip - mean_I * mean_p

    mean_II = cv2.boxFilter(im * im, cv2.CV_64F, (r, r))
    var_I = mean_II - mean_I * mean_I

    a = cov_Ip / (var_I + eps)
    b = mean_p - a * mean_I
    
    mean_a = cv2.boxFilter(a, cv2.CV_64F, (r, r))
    mean_b = cv2.boxFilter(b, cv2.CV_64F, (r, r))
   
    q = mean_a * im + mean_b
    return q

def TransmissionRefine(im, et): 
    """Affinage de la transmission guidé par l'image source convertie en niveaux de gris"""
    gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    gray = np.float64(gray) / 255.0
    r = 60
    eps = 0.0001
    return Guidedfilter(gray, et, r, eps)

def Recover(im, t, A, tx=0.1):
    """Restauration finale du spectre de l'image (éclat J) sans altération""" 
    res = np.empty(im.shape, im.dtype)
    tt = cv2.max(t, tx)
    for ind in range(0, 3):
        res[:, :, ind] = (im[:, :, ind] - A[0, ind]) / tt + A[0, ind]
    return res

def atm_calculation(II):
    """Fonction isolée d'analyse atmosphérique pour l'air standard"""
    srcc = BGR2Float(II)
    dark = DarkChannel(srcc, 15)
    return AtmLight(srcc, dark)

def water_calculation(II):
    """Fonction isolée d'analyse atmosphérique adaptée à l'eau"""
    srcc = BGR2Float(II)
    dark = DarkChannelWater(srcc, 15)
    return AtmLight(srcc, dark)

def process_image_dehaze(II, A, is_water=False): 
    """Pipeline complet pour supprimer le voile de brume ou le flou aquatique"""
    try:
        srcc = BGR2Float(II)
        te = TransmissionEstimate(srcc, A, 15, is_water=is_water)
        t = TransmissionRefine(II, te) 
        III = Recover(srcc, t, A, 0.1)     
        return Float2BGR(III)
    except Exception as e:
        print(f"Erreur lors du débrumage: {e}")
        return II


# ============================================================================
# EXPLORATION DES SUPPORTS DE CAMPAGNE (JSON, GPS, FILES)
# ============================================================================

def get_all_mp4_files(dossier_parent):
    """Scane le dossier campagne pour récupérer les infos de toutes les vidéos MP4."""
    video_data = []
    for root, dirs, files in os.walk(dossier_parent):
        if "trash" in root.split(os.sep):
            continue
            
        for file in files:
            if file.lower().endswith(".mp4"):
                full_path = os.path.join(root, file)
                
                try:
                    taille_octets = os.path.getsize(full_path)
                    taille_mo = taille_octets / (1024 * 1024)
                    taille_str = f"{taille_mo:.2f} Mo"
                except Exception:
                    taille_str = "-- Mo"
                
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
                        "size": taille_str
                    })
                    cap.release()
                else:
                    video_data.append({
                        "name": file, 
                        "path": full_path, 
                        "duration": "--", 
                        "fps": "--", 
                        "res": "--",
                        "size": taille_str
                    })
                        
    video_data.sort(key=lambda x: x["name"])
    return video_data


def get_video_gps_coords(video_path):
    """Lit le fichier CSV lié à la vidéo pour en extraire la première coordonnée GPS."""
    csv_gps = video_path.replace(".mp4", ".csv")
    if os.path.exists(csv_gps):
        try:
            df = pd.read_csv(csv_gps, sep=None, engine='python')
            df.columns = [c.strip().lower() for c in df.columns]
            
            if 'lat' in df.columns and 'long' in df.columns:
                lat = float(df['lat'].iloc[0])
                lon = float(df['long'].iloc[0])
                return lat, lon
            else:
                print(f"Colonnes GPS manquantes dans {csv_gps}. Trouvées : {list(df.columns)}")
        except Exception as e:
            print(f"Erreur lors de la lecture du GPS : {e}")
    return None


def get_campaign_json_data(dossier_campagne, extract_system=False):
    """Parcourt les sous-dossiers de la campagne à la recherche de template.json"""
    if not dossier_campagne or not os.path.exists(dossier_campagne):
        return None
        
    for root, dirs, files in os.walk(dossier_campagne):
        if "trash" in root.split(os.sep):
            continue
            
        if "template.json" in files:
            json_path = os.path.join(root, "template.json")
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    donnees_completes = json.load(f)
                
                if extract_system:
                    if "system" in donnees_completes:
                        print(f"[UTILS2] Bloc 'system' extrait avec succès depuis : {json_path}")
                        return donnees_completes["system"]
                    else:
                        print(f"[WARNING UTILS2] Fichier trouvé mais aucun bloc 'system' à l'intérieur de {json_path}")
                        return None
                
                print(f"[UTILS2] JSON complet chargé avec succès depuis : {json_path}")
                return donnees_completes

            except Exception as e:
                print(f"[ERROR UTILS2] Échec de la lecture du JSON sur {json_path} : {e}")
                
    print("[WARNING UTILS2] Aucun fichier 'template.json' trouvé dans toute la campagne.")
    return None