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


def convert_to_douglas(wave_height) -> str:
    """Convertit une hauteur de vague en échelle de Douglas (0-9)."""
    if wave_height is None: return "0"
    if wave_height == 0: return "0"
    elif wave_height <= 0.1: return "1"
    elif wave_height <= 0.5: return "2"
    elif wave_height <= 1.25: return "3"
    elif wave_height <= 2.5: return "4"
    elif wave_height <= 4.0: return "5"
    elif wave_height <= 6.0: return "6"
    elif wave_height <= 9.0: return "7"
    elif wave_height <= 14.0: return "8"
    else: return "9"


def degrees_to_compass_rose(degrees, language="fr") -> str:
    """Convertit des degrés (0-360) en notation de rose des vents."""
    if degrees is None: return "N"
    directions_fr = ["N", "NE", "E", "SE", "S", "So", "O", "NO"]
    directions_en = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    index = int((degrees + 22.5) / 45) % 8
    return directions_fr[index] if language == "fr" else directions_en[index]


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

def fetch_marine_weather_metadata(lat, lon, iso_date: str = None, language="fr") -> dict:
    """Interroge l'API Open-Meteo (Forecast ou Archive) et retourne un dict formaté.

    Args:
        lat: Latitude.
        lon: Longitude.
        iso_date: Date ISO (YYYY-MM-DD ou avec heure).
        language: 'fr' ou 'en'.

    Returns:
        Dict avec clés météo, ou None en cas d'erreur.
    """
    try:
        lat_clean = float(str(lat).replace(",", "."))
        lon_clean = float(str(lon).replace(",", "."))
    except (ValueError, TypeError):
        print(f"[WEATHER ERROR] Coordonnées invalides : Lat={lat}, Lon={lon}")
        return None

    target_hour = None
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

    if target_hour is None:
        target_hour = 12

    endpoint_url = "https://api.open-meteo.com/v1/forecast"
    try:
        date_obj = datetime.strptime(date_only, "%Y-%m-%d")
        if date_obj < (datetime.now() - timedelta(days=85)):
            endpoint_url = "https://archive-api.open-meteo.com/v1/archive"
    except Exception as e:
        print(f"[WEATHER API] Impossible d'évaluer l'âge de la date : {e}")

    url = (
        f"{endpoint_url}?"
        f"latitude={lat_clean}&longitude={lon_clean}"
        f"&start_date={date_only}&end_date={date_only}"
        f"&hourly=temperature_2m,wind_speed_10m,wind_direction_10m,weather_code,"
        f"wave_height,swell_wave_height,swell_wave_direction,sea_surface_temperature"
        f"&cell_selection=sea&timezone=auto"
    )

    print(f"[WEATHER API] Requête : {url}")
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})

    try:
        with urllib.request.urlopen(req) as response:
            payload = json.loads(response.read().decode())

            if "hourly" not in payload:
                print("[WEATHER ERROR] Structure de réponse API incorrecte.")
                return None

            hourly_data = payload["hourly"]

            target_index = 0
            for i, time_str in enumerate(hourly_data.get("time", [])):
                if f"T{target_hour:02d}:00" in time_str:
                    target_index = i
                    break

            wind_kmh = hourly_data.get("wind_speed_10m", [0] * 24)[target_index] or 0
            wind_degrees = hourly_data.get("wind_direction_10m", [0] * 24)[target_index] or 0
            sky_code = hourly_data.get("weather_code", [0] * 24)[target_index] or 0
            wave_height = hourly_data.get("wave_height", [0] * 24)[target_index] or 0
            swell_height = hourly_data.get("swell_wave_height", [0] * 24)[target_index] or 0
            swell_direction_degrees = hourly_data.get("swell_wave_direction", [0] * 24)[target_index] or 0

            return {
                "airTemp": float(hourly_data["temperature_2m"][target_index])
                           if hourly_data["temperature_2m"][target_index] is not None else 0.0,
                "wind": int(convert_to_beaufort(wind_kmh)),
                "wind_direction": str(degrees_to_compass_rose(wind_degrees, language)),
                "weather": str(interpret_wmo_weather_code(sky_code, language)),
                "seaState": str(convert_to_douglas(wave_height)),
                "water_temperature": float(hourly_data["sea_surface_temperature"][target_index])
                                     if hourly_data.get("sea_surface_temperature")
                                     and hourly_data["sea_surface_temperature"][target_index] is not None
                                     else None,
                "swell_height": f"{swell_height} m" if swell_height is not None else "0.0 m",
                "swell_direction": str(degrees_to_compass_rose(swell_direction_degrees, language))
            }

    except urllib.error.HTTPError as e:
        print(f"[WEATHER API ERROR] Code {e.code}: {e.reason}")
        return None
    except Exception as e:
        print(f"[WEATHER ERROR] Erreur inattendue : {e}")
        return None


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
