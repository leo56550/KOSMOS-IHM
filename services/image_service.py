import math
import cv2
import numpy as np


def extract_frame_at_time(video_path: str, timestamp_seconds: float) -> np.ndarray:
    """Extrait une frame RGB depuis une vidéo à un timestamp donné.

    Args:
        video_path: Chemin vers le fichier vidéo.
        timestamp_seconds: Position en secondes dans le flux.

    Returns:
        Tableau numpy RGB, ou None si l'extraction échoue.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Impossible d'ouvrir le flux vidéo : {video_path}")
        return None

    time_in_ms = int(timestamp_seconds * 1000)
    cap.set(cv2.CAP_PROP_POS_MSEC, time_in_ms)
    success, frame = cap.read()
    cap.release()

    if success and frame is not None:
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    else:
        print(f"Échec extraction à {timestamp_seconds}s ({time_in_ms}ms)")
        return None


# ============================================================================
# Utilitaires flottants
# ============================================================================

def bgr_to_float(src: np.ndarray) -> np.ndarray:
    return src.astype('float64') / 255.0


def float_to_bgr(img: np.ndarray) -> np.ndarray:
    return np.clip(img * 255, 0, 255).astype('uint8')


# ============================================================================
# Histogram Equalization
# ============================================================================

def _analyze_histogram(img: np.ndarray) -> tuple:
    mean_b = np.median(img[:, :, 0])
    mean_g = np.median(img[:, :, 1])
    mean_r = np.median(img[:, :, 2])
    std_b = np.std(img[:, :, 0])
    std_g = np.std(img[:, :, 1])
    std_r = np.std(img[:, :, 2])
    return [mean_b, mean_g, mean_r], [std_b, std_g, std_r]


def process_image_he(img: np.ndarray, v_b: float = 2.0, v_g: float = 2.0, v_r: float = 2.0) -> np.ndarray:
    """Applique une égalisation d'histogramme par balance moyenne/variance."""
    try:
        [[mean_b, mean_g, mean_r], [std_b, std_g, std_r]] = _analyze_histogram(img)
        enhanced = np.zeros(img.shape, dtype=np.float64)

        sq_b = max(std_b, 1e-5)
        sq_g = max(std_g, 1e-5)
        sq_r = max(std_r, 1e-5)

        enhanced[:, :, 0] = (img[:, :, 0] - mean_b + v_b * sq_b) / (2 * v_b * sq_b)
        enhanced[:, :, 1] = (img[:, :, 1] - mean_g + v_g * sq_g) / (2 * v_g * sq_g)
        enhanced[:, :, 2] = (img[:, :, 2] - mean_r + v_r * sq_r) / (2 * v_r * sq_r)

        return float_to_bgr(enhanced)
    except Exception as e:
        print(f"Erreur égalisation histogramme : {e}")
        return img


# ============================================================================
# Dehaze (Dark Channel Prior)
# ============================================================================

def dark_channel(im: np.ndarray, size: int) -> np.ndarray:
    b, g, r = cv2.split(im)
    dc = cv2.min(cv2.min(r, g), b)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (size, size))
    return cv2.erode(dc, kernel)


def dark_channel_water(im: np.ndarray, size: int) -> np.ndarray:
    b, g, _ = cv2.split(im)
    dc = cv2.min(g, b)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (size, size))
    return cv2.erode(dc, kernel)


def atm_light(im: np.ndarray, dark: np.ndarray) -> np.ndarray:
    h, w = im.shape[:2]
    total_pixels = h * w
    num_pixels = int(max(math.floor(total_pixels / 1000), 1))
    dark_vector = dark.reshape(total_pixels)
    img_vector = im.reshape(total_pixels, 3)
    indices = dark_vector.argsort()[total_pixels - num_pixels:]
    return np.mean(img_vector[indices], axis=0).reshape(1, 3)


def calculate_atmospheric_light(img: np.ndarray) -> np.ndarray:
    floated = bgr_to_float(img)
    dark = dark_channel(floated, 15)
    return atm_light(floated, dark)


def calculate_water_light(img: np.ndarray) -> np.ndarray:
    floated = bgr_to_float(img)
    dark = dark_channel_water(floated, 15)
    return atm_light(floated, dark)


def _transmission_estimate(im: np.ndarray, a_vector: np.ndarray, size: int, is_water: bool = False) -> np.ndarray:
    omega = 0.6
    a_safe = np.where(a_vector == 0, 1e-5, a_vector)
    normalized = im / a_safe
    if is_water:
        dark = dark_channel_water(normalized, size)
    else:
        dark = dark_channel(normalized, size)
    return 1.0 - omega * dark


def _guided_filter(guide: np.ndarray, source_p: np.ndarray, radius: int, eps: float) -> np.ndarray:
    mean_i = cv2.boxFilter(guide, cv2.CV_64F, (radius, radius))
    mean_p = cv2.boxFilter(source_p, cv2.CV_64F, (radius, radius))
    mean_ip = cv2.boxFilter(guide * source_p, cv2.CV_64F, (radius, radius))
    cov_ip = mean_ip - mean_i * mean_p
    mean_ii = cv2.boxFilter(guide * guide, cv2.CV_64F, (radius, radius))
    var_i = mean_ii - mean_i * mean_i
    a_coef = cov_ip / (var_i + eps)
    b_coef = mean_p - a_coef * mean_i
    mean_a = cv2.boxFilter(a_coef, cv2.CV_64F, (radius, radius))
    mean_b = cv2.boxFilter(b_coef, cv2.CV_64F, (radius, radius))
    return mean_a * guide + mean_b


def _transmission_refine(im: np.ndarray, estimated_t: np.ndarray) -> np.ndarray:
    gray = np.float64(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)) / 255.0
    return _guided_filter(gray, estimated_t, 60, 0.0001)


def _recover_radiance(im: np.ndarray, transmission_map: np.ndarray, a_vector: np.ndarray,
                      t_floor: float = 0.1) -> np.ndarray:
    res = np.empty(im.shape, im.dtype)
    bounded_t = cv2.max(transmission_map, t_floor)
    for ind in range(3):
        res[:, :, ind] = (im[:, :, ind] - a_vector[0, ind]) / bounded_t + a_vector[0, ind]
    return res


def process_image_dehaze(img: np.ndarray, a_vector: np.ndarray, is_water: bool = False) -> np.ndarray:
    """Pipeline complet de débrumage (Dark Channel Prior).

    Args:
        img: Image source BGR.
        a_vector: Vecteur de lumière atmosphérique pré-calculé.
        is_water: Active les ajustements sous-marins.

    Returns:
        Image débrumée BGR.
    """
    try:
        floated = bgr_to_float(img)
        raw_t = _transmission_estimate(floated, a_vector, 15, is_water=is_water)
        refined_t = _transmission_refine(img, raw_t)
        restored = _recover_radiance(floated, refined_t, a_vector, 0.1)
        return float_to_bgr(restored)
    except Exception as e:
        print(f"Erreur pipeline dehaze : {e}")
        return img
