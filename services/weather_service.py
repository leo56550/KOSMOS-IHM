import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from PyQt6.QtCore import QThread, pyqtSignal


# ============================================================================
# Fonctions de conversion
# ============================================================================

def convert_to_beaufort(speed_kmh) -> int:
    """Convertit une vitesse de vent km/h en échelle de Beaufort (0-12)."""
    if speed_kmh < 1: return 0
    elif speed_kmh <= 5: return 1
    elif speed_kmh <= 11: return 2
    elif speed_kmh <= 19: return 3
    elif speed_kmh <= 28: return 4
    elif speed_kmh <= 38: return 5
    elif speed_kmh <= 49: return 6
    elif speed_kmh <= 61: return 7
    elif speed_kmh <= 74: return 8
    elif speed_kmh <= 88: return 9
    elif speed_kmh <= 102: return 10
    elif speed_kmh <= 117: return 11
    else: return 12


def convert_to_douglas(wave_height) -> int:
    """Convertit une hauteur de vague en échelle de Douglas (0-9, int)."""
    if wave_height is None or wave_height == 0: return 0
    elif wave_height <= 0.1: return 1
    elif wave_height <= 0.5: return 2
    elif wave_height <= 1.25: return 3
    elif wave_height <= 2.5: return 4
    elif wave_height <= 4.0: return 5
    elif wave_height <= 6.0: return 6
    elif wave_height <= 9.0: return 7
    elif wave_height <= 14.0: return 8
    else: return 9


def degrees_to_compass_rose(degrees, language="fr") -> str:
    """Convertit des degrés (0-360) en notation de rose des vents (valeurs autorisées JSON)."""
    if degrees is None: return "N"
    directions_fr = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]
    directions_en = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    index = int((degrees + 22.5) / 45) % 8
    return directions_fr[index] if language == "fr" else directions_en[index]


def get_moon_phase(date_str: str, language="fr") -> str:
    """Calcule la phase lunaire depuis une date ISO (YYYY-MM-DD) — valeurs autorisées JSON."""
    phases_fr = [
        "Nouvelle Lune", "Premier Croissant", "Premier Quartier",
        "Gibbeuse Croissante", "Pleine Lune", "Gibbeuse Décroissante",
        "Dernier Quartier", "Dernier croissant",
    ]
    phases_en = [
        "New Moon", "Waxing Crescent", "First Quarter",
        "Waxing Gibbous", "Full Moon", "Waning Gibbous",
        "Last Quarter", "Waning Crescent",
    ]
    try:
        target = datetime.strptime(date_str[:10], "%Y-%m-%d")
        known_new_moon = datetime(2000, 1, 6)
        diff_days = (target - known_new_moon).days % 29.53059
        phase_idx = int(diff_days / (29.53059 / 8)) % 8
        return phases_fr[phase_idx] if language == "fr" else phases_en[phase_idx]
    except Exception:
        return None


def interpret_wmo_weather_code(code, language="fr") -> str:
    """Traduit un code météo WMO en texte lisible."""
    if language == "fr":
        if code in [0, 1]: return "Soleil"
        elif code in [2, 3]: return "Nuageux"
        elif code in [45, 48]: return "Brouillard"
        elif code in [51, 53, 55, 61, 63, 65]: return "Pluie"
        elif code in [71, 73, 75, 77, 85, 86]: return "Neige"
        elif code in [80, 81, 82]: return "Averses"
        elif code in [95, 96, 99]: return "Orage"
        else: return "Variable"
    else:
        if code in [0, 1]: return "Sunny"
        elif code in [2, 3]: return "Cloudy"
        elif code in [45, 48]: return "Foggy"
        elif code in [51, 53, 55, 61, 63, 65]: return "Rain"
        elif code in [71, 73, 75, 77, 85, 86]: return "Snow"
        elif code in [80, 81, 82]: return "Showers"
        elif code in [95, 96, 99]: return "Thunderstorm"
        else: return "Variable"


# ============================================================================
# Appel API Open-Meteo
# ============================================================================

def _fetch_url(url: str) -> dict | None:
    """Effectue une requête GET et retourne le JSON parsé, ou None en cas d'erreur."""
    print(f"[WEATHER API] Requête : {url}")
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        print(f"[WEATHER API ERROR] Code {e.code}: {e.reason}")
    except Exception as e:
        print(f"[WEATHER ERROR] Erreur inattendue : {e}")
    return None


def _hourly_value(hourly: dict, key: str, idx: int, default=0):
    """Retourne hourly[key][idx] ou default si absent/None."""
    vals = hourly.get(key)
    if vals and idx < len(vals) and vals[idx] is not None:
        return vals[idx]
    return default


def fetch_marine_weather_metadata(lat, lon, iso_date: str = None, language="fr") -> dict:
    """Interroge Open-Meteo (Forecast/Archive + Marine) et retourne un dict formaté.

    Deux appels séparés :
      1. API atmosphérique (forecast ou archive) → température air, vent, ciel.
      2. API marine (marine-api.open-meteo.com)  → vagues, houle, température eau.
    """
    try:
        lat_clean = float(str(lat).replace(",", "."))
        lon_clean = float(str(lon).replace(",", "."))
    except (ValueError, TypeError):
        print(f"[WEATHER ERROR] Coordonnées invalides : Lat={lat}, Lon={lon}")
        return None

    # ── Résolution de la date et de l'heure cible ────────────────────────
    target_hour = 12
    if iso_date:
        try:
            if "T" in iso_date:
                dt = datetime.fromisoformat(iso_date)
                date_only = dt.strftime("%Y-%m-%d")
                target_hour = dt.hour
            elif " " in iso_date:
                dt = datetime.strptime(iso_date.split(".")[0], "%Y-%m-%d %H:%M:%S")
                date_only = dt.strftime("%Y-%m-%d")
                target_hour = dt.hour
            else:
                date_only = str(iso_date).strip()
        except Exception as e:
            print(f"[WEATHER] Format de date invalide ({iso_date}) : {e}")
            date_only = datetime.now().strftime("%Y-%m-%d")
    else:
        date_only = datetime.now().strftime("%Y-%m-%d")

    # ── Choix endpoint atmosphérique (forecast récent ou archive) ────────
    atmo_endpoint = "https://api.open-meteo.com/v1/forecast"
    try:
        date_obj = datetime.strptime(date_only, "%Y-%m-%d")
        if date_obj < (datetime.now() - timedelta(days=7)):
            atmo_endpoint = "https://archive-api.open-meteo.com/v1/archive"
    except Exception as e:
        print(f"[WEATHER API] Impossible d'évaluer l'âge de la date : {e}")

    date_param = f"start_date={date_only}&end_date={date_only}"

    # ── 1. Appel atmosphérique ────────────────────────────────────────────
    atmo_url = (
        f"{atmo_endpoint}?latitude={lat_clean}&longitude={lon_clean}"
        f"&{date_param}"
        f"&hourly=temperature_2m,wind_speed_10m,wind_direction_10m,weather_code"
        f"&timezone=auto"
    )
    atmo_payload = _fetch_url(atmo_url)
    atmo = atmo_payload.get("hourly", {}) if atmo_payload else {}

    # ── 2. Appel marine ───────────────────────────────────────────────────
    marine_url = (
        f"https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={lat_clean}&longitude={lon_clean}"
        f"&{date_param}"
        f"&hourly=wave_height,swell_wave_height,swell_wave_direction,sea_surface_temperature"
        f"&timezone=auto"
    )
    marine_payload = _fetch_url(marine_url)
    marine = marine_payload.get("hourly", {}) if marine_payload else {}

    if not atmo and not marine:
        print("[WEATHER ERROR] Aucune donnée reçue (les deux appels ont échoué).")
        return None

    # ── Indice horaire ────────────────────────────────────────────────────
    target_index = 0
    for i, time_str in enumerate(atmo.get("time", []) or marine.get("time", [])):
        if f"T{target_hour:02d}:00" in time_str:
            target_index = i
            break

    wind_kmh   = _hourly_value(atmo, "wind_speed_10m",      target_index, 0)
    wind_deg   = _hourly_value(atmo, "wind_direction_10m",   target_index, 0)
    sky_code   = _hourly_value(atmo, "weather_code",         target_index, 0)
    air_temp   = _hourly_value(atmo, "temperature_2m",       target_index, None)

    wave_h     = _hourly_value(marine, "wave_height",          target_index, 0)
    swell_h    = _hourly_value(marine, "swell_wave_height",    target_index, 0)
    swell_deg  = _hourly_value(marine, "swell_wave_direction", target_index, 0)
    water_temp = _hourly_value(marine, "sea_surface_temperature", target_index, None)

    result = {
        # ── Priorité 1 : Lune (calculée depuis la date, pas d'API externe) ──
        "moon":            get_moon_phase(date_only, language),
        # ── Priorité 2 : Météo / Vent ──────────────────────────────────────
        "weather":         interpret_wmo_weather_code(sky_code, language),
        "wind":            int(convert_to_beaufort(wind_kmh)),
        "wind_direction":  degrees_to_compass_rose(wind_deg, language),
        # ── Priorité 3 : Mer / Houle (API marine) ──────────────────────────
        "seaState":        convert_to_douglas(wave_h),          # int 0-9
        "swell_height":    int(round(swell_h)) if swell_h else 0,  # int mètres
        "swell_direction": degrees_to_compass_rose(swell_deg, language),
        # ── Autres ─────────────────────────────────────────────────────────
        "airTemp":         round(float(air_temp), 1) if air_temp is not None else None,
        "water_temperature": round(float(water_temp), 1) if water_temp is not None else None,
        # tide / coefficient : non disponibles via Open-Meteo → non inclus
    }
    # Retire les None pour ne pas écraser des valeurs existantes
    return {k: v for k, v in result.items() if v is not None}


# ============================================================================
# Worker asynchrone
# ============================================================================

class WeatherWorker(QThread):
    """Thread background pour récupérer les données météo depuis l'API Open-Meteo."""

    weather_fetched = pyqtSignal(dict, str)

    def __init__(self, lat, lon, iso_date=None, language="fr"):
        """Prépare le worker avec les coordonnées GPS, la date optionnelle et la langue."""
        super().__init__()
        self.lat = lat
        self.lon = lon
        self.iso_date = iso_date
        self.language = language

    def run(self):
        """Appelle l'API Open-Meteo en arrière-plan et émet `weather_fetched` avec le résultat."""
        result = fetch_marine_weather_metadata(self.lat, self.lon, self.iso_date, self.language)
        resolved_date = self.iso_date if self.iso_date else datetime.now().strftime("%Y-%m-%d")
        self.weather_fetched.emit(result if result else {}, resolved_date)
