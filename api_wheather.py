import urllib.request
import json
# --- AJOUT DE L'IMPORT QT POUR LE THREAD ---
from PyQt6 import QtCore

def Beaufort(vitesse_kmh):
    """Convertit la vitesse du vent de km/h vers l'Échelle de Beaufort (0-12)."""
    if vitesse_kmh < 1: return 0
    elif vitesse_kmh <= 5: return 1
    elif vitesse_kmh <= 11: return 2
    elif vitesse_kmh <= 19: return 3
    elif vitesse_kmh <= 28: return 4
    elif vitesse_kmh <= 38: return 5
    elif vitesse_kmh <= 49: return 6
    elif vitesse_kmh <= 61: return 7
    elif vitesse_kmh <= 74: return 8
    elif vitesse_kmh <= 88: return 9
    elif vitesse_kmh <= 102: return 10
    elif vitesse_kmh <= 117: return 11
    else: return 12

def douglas(hauteur_vagues):
    """Convertit la hauteur des vagues en Échelle de Douglas (0-9) pour seaState."""
    if hauteur_vagues is None: return "0"
    if hauteur_vagues == 0: return "0"
    elif hauteur_vagues <= 0.1: return "1"
    elif hauteur_vagues <= 0.5: return "2"
    elif hauteur_vagues <= 1.25: return "3"
    elif hauteur_vagues <= 2.5: return "4"
    elif hauteur_vagues <= 4.0: return "5"
    elif hauteur_vagues <= 6.0: return "6"
    elif hauteur_vagues <= 9.0: return "7"
    elif hauteur_vagues <= 14.0: return "8"
    else: return "9"

def degres_vers_rose_des_vents(degres, langue="fr"):
    """Convertit des degrés (0-360) en direction textuelle (N, NE, E, SE, S, SO, O, NO)."""
    if degres is None: return "N"
    directions_fr = ["N", "NE", "E", "SE", "S", "So", "O", "NO"]
    directions_en = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    
    index = int((degres + 22.5) / 45) % 8
    return directions_fr[index] if langue == "fr" else directions_en[index]

def interpreter_weather_code(code):
    """Traduit le Weather Code de l'OMM en texte simple pour le champ 'weather'."""
    if code in [0, 1]: return "Soleil"
    elif code in [2, 3]: return "Nuageux"
    elif code in [45, 48]: return "Brouillard"
    elif code in [51, 53, 55, 61, 63, 65]: return "Pluie"
    elif code in [71, 73, 75, 77, 85, 86]: return "Neige"
    elif code in [80, 81, 82]: return "Averses"
    elif code in [95, 96, 99]: return "Orage"
    else: return "Variable"

def recuperer_metadonnees_meteo_marine(lat, lon):
    """Interroge Open-Meteo et renvoie un dictionnaire formaté."""
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&hourly=temperature_2m,wind_speed_10m,wind_direction_10m,weather_code,"
        f"wave_height,swell_wave_height,swell_wave_direction,sea_surface_temperature"
        f"&forecast_days=1"
        f"&cell_selection=sea"
    )
    
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    
    try:
        with urllib.request.urlopen(req) as response:
            donnees = json.loads(response.read().decode())
            
            if "hourly" not in donnees:
                print("[ERREUR] Structure de réponse API incorrecte.")
                return None
                
            hourly = donnees["hourly"]
            idx = 0 
            
            vent_kmh = hourly["wind_speed_10m"][idx]
            vent_degres = hourly["wind_direction_10m"][idx]
            code_ciel = hourly["weather_code"][idx]
            hauteur_vagues = hourly["wave_height"][idx]
            hauteur_houle = hourly["swell_wave_height"][idx]
            direction_houle_degres = hourly["swell_wave_direction"][idx]
            
            resultats_json = {
                "airTemp": float(hourly["temperature_2m"][idx]),
                "wind": int(Beaufort(vent_kmh)),
                "wind_direction": str(degres_vers_rose_des_vents(vent_degres)),
                "weather": str(interpreter_weather_code(code_ciel)),
                "seaState": str(douglas(hauteur_vagues)),
                "water_temperature": float(hourly["sea_surface_temperature"][idx]) if hourly["sea_surface_temperature"][idx] is not None else None,
                "swell_height": f"{hauteur_houle} m" if hauteur_houle is not None else "0.0 m",
                "swell_direction": str(degres_vers_rose_des_vents(direction_houle_degres))
            }
            
            return resultats_json
            
    except Exception as e:
        print(f"[ERREUR API] Impossible de récupérer la météo : {e}")
        return None

# =========================================================================
# --- WORKER AJOUTÉ EN BAS DU FICHIER SÉPARÉ ---
# =========================================================================

class WeatherWorker(QtCore.QThread):
    """Thread secondaire pour interroger l'API météo sans bloquer l'IHM."""
    meteo_recuperee = QtCore.pyqtSignal(dict)

    def __init__(self, lat, lon):
        super().__init__()
        self.lat = lat
        self.lon = lon

    def run(self):
        # Le thread appelle directement la fonction locale du fichier
        resultat = recuperer_metadonnees_meteo_marine(self.lat, self.lon)
        if resultat:
            self.meteo_recuperee.emit(resultat)
        else:
            self.meteo_recuperee.emit({})