"""Converts legacy template.json (v3-style flat dicts) to the current rich-field format."""

import json
import os


def is_legacy_format(data: dict) -> bool:
    """Return True if *data* uses the old flat dict structure (pre-v4 rich fields)."""
    if not isinstance(data, dict):
        return False
    video = data.get("video", {})
    return isinstance(video, dict) and "gpsDict" in video


def _build_base_template() -> dict:
    """Return the full new-format template with value=null everywhere."""
    events_deployment_schema = {
        "event_id": None, "time_code_start": None, "time_code_end": None,
        "frame_number_start": None, "frame_number_end": None,
        "description_fr": None, "description_en": None,
        "authorized_values_en": ["landing", "take_off", "whiteboard", "rotation", "annotation_start"],
        "authorized_values_fr": ["atterrissage", "décollage", "tableau blanc", "rotation", "début_annotation"],
        "values": []
    }
    events_animal_schema = {
        "event_id": None, "time_code_start": None, "time_code_end": None,
        "frame_number_start": None, "frame_number_end": None,
        "description_fr": None, "description_en": None,
        "authorized_values_en": ["fish", "mammal", "crustacean", "cephalopod", "turtle", "bird", "other"],
        "authorized_values_fr": ["poisson", "mammifère", "crustacean", "cephalopod", "tortue", "oiseau", "autre"],
        "values": []
    }
    events_images_schema = {
        "event_id": None, "time_code_start": None, "frame_number": None,
        "description_fr": None, "description_en": None,
        "authorized_values_en": ["habitat", "behavior", "anthropogenic", "other"],
        "authorized_values_fr": ["habitat", "behavior", "anthropogenic", "other"],
        "values": []
    }

    return {
        "system": {
            "camera": {
                "name": "Camera", "name_fr": "Caméra", "type": "str",
                "format": "Alphanumérique", "value": None,
                "description": "The type of camera used and its identification number",
                "description_fr": "Le type de caméra utilisée et son numéro",
                "acquisition_mode": "System", "example": "CX900, PLZ, ….",
                "authorized_values": None, "unity": None, "sensor": "Sony IMX477",
                "resolution": None, "ifdo_id": None
            },
            "model_mcu": {
                "name": "MCU Model", "name_fr": "Modèle de l'unité de calcul", "type": "str",
                "format": "Alphanumérique", "value": None,
                "description": "Identification of the computing unit/system used for this video",
                "description_fr": "Identification du système utilisé pour cette vidéo",
                "acquisition_mode": "System", "example": "Raspberry Pi 5", "ifdo_id": None
            },
            "type_system": {
                "name": "System", "name_fr": "Système", "type": "str",
                "format": "Texte", "value": None,
                "description": "Identification of the overall system configuration",
                "description_fr": "Identification du système utilisé pour cette vidéo",
                "acquisition_mode": "System", "example": "STAVIRO, KOSMOS, Kstereo, Transect bar",
                "ifdo_id": None
            },
            "system_version": {
                "name": "Version", "name_fr": "Version", "type": "str",
                "format": "Alphanumérique", "value": None,
                "description": "KOSMOS version used for this video",
                "description_fr": "Version du KOSMOS utilisé pour cette vidéo",
                "acquisition_mode": "System", "example": "4.0", "ifdo_id": None
            }
        },
        "survey": {
            "survey_name": {
                "name": "Survey", "name_fr": "campagne", "type": "str",
                "format": "Alphanumérique", "value": None,
                "description": "Name of the survey",
                "description_fr": "Nom de la campagne en mer",
                "acquisition_mode": "Web application",
                "example": "CC2025 (Concarneau survey 2025)", "ifdo_id": None
            },
            "zone": {
                "name": "Zone", "name_fr": "Zone", "type": "str",
                "format": "Numerical 2 or 3 letters", "value": None,
                "description": "Geographical area of the survey",
                "description_fr": "Zone géographique de la campagne",
                "acquisition_mode": "Web application",
                "example": "Concarneau : CC, Cote bleue : CB, Banyuls : BA", "ifdo_id": None
            },
            "site": {
                "name": "Site", "name_fr": "Site", "type": "str",
                "format": "Texte", "value": None,
                "description": "Site within the zone",
                "description_fr": "Site de la campagne",
                "acquisition_mode": "Field Sheet/Aposteriori",
                "example": "Glénan", "ifdo_id": None
            },
            "region": {
                "name": "Region", "name_fr": "Région", "type": "str",
                "format": "Texte", "value": None,
                "description": "Region of the survey",
                "description_fr": "ATL -> Atlantique, MED -> Méditerranéean",
                "acquisition_mode": "IHM", "example": "ATL", "ifdo_id": None
            },
            "type": {
                "name": "Type", "name_fr": "Type", "type": "str",
                "format": "Texte", "value": None,
                "description": "Type of the observation unit used",
                "description_fr": "Type de l'unité d'observation",
                "acquisition_mode": "IHM",
                "example": "Staviro (SVR), Micado (MIC), Transect vidéo (TRV), Non-rotating",
                "ifdo_id": None
            },
            "protectionStatus1": {
                "name": "Protection Status 1", "name_fr": "Statut de protection 1", "type": "str",
                "format": "Alphanumérique (RI, RE, PP, HR)", "value": None,
                "description": "Protection status of the observation site",
                "description_fr": "Statut de protection où se trouve l'observation",
                "acquisition_mode": "Aposteriori",
                "example": "RI (réserve intégrale), PP (protection partielle)",
                "ifdo_id": None,
                "authorized_values_en": ["RE", "HR", "RP", "RI"],
                "authorized_values_fr": ["RE", "HR", "PP", "RI"]
            },
            "protectionStatus2": {
                "name": "Protection Status 2", "name_fr": "Statut de protection 2", "type": "str",
                "format": "Alphanumérique", "value": None,
                "description": "Secondary protection status of the observation site",
                "description_fr": "Autre statut de protection où se trouve l'observation",
                "acquisition_mode": "Aposteriori",
                "example": "PM (patrimoine mondial), WH (world heritage), N2000, RNN, PNM",
                "ifdo_id": None
            },
            "date": {
                "name": "Date", "name_fr": "Date", "type": "str",
                "format": "Text YYYYMMDD", "value": None,
                "description": "Execution date of the observation",
                "description_fr": "Date de réalisation de l'observation",
                "acquisition_mode": "Web application/Sensor",
                "example": "20250118", "ifdo_id": None
            },
            "boat_name": {
                "name": "Boat Name", "name_fr": "Nom du bateau", "type": "str",
                "format": "Texte", "value": None,
                "description": "Name of the vessel used",
                "description_fr": "Nom du navire utilisé",
                "acquisition_mode": "Web application", "example": "Enezeg", "ifdo_id": None
            },
            "pilot_name": {
                "name": "Pilot Name", "name_fr": "Nom du pilote", "type": "str",
                "format": "Texte", "value": None,
                "description": "Name of the pilot or operator",
                "description_fr": "Nom du pilote",
                "acquisition_mode": "Web application", "example": "Olivier Fauvarque", "ifdo_id": None
            },
            "crew_names": {
                "name": "Crew Names", "name_fr": "Nom des membres de l'équipage", "type": "str",
                "format": "Texte", "value": None,
                "description": "List of crew member names",
                "description_fr": "Liste de noms de l'équipage",
                "acquisition_mode": "Web application",
                "example": "Olivier Fauvarque Léo Bultel Robin Bars", "ifdo_id": None
            }
        },
        "video_observation": {
            "monitoring_program": {
                "name": "Monitoring Program", "name_fr": "Programme de suivi", "type": "str",
                "format": "Texte", "value": None,
                "description": "Indicates if this station is part of another monitoring program and its type",
                "description_fr": "Cette station fait elle l'objet d'un autre suivi, si oui de quel type",
                "acquisition_mode": "Aposteriori", "example": "Suivi Illien", "ifdo_id": None
            },
            "codeObs": {
                "name": "codeObs", "name_fr": "codeObs", "type": "str",
                "format": "Alphanumérique (Zone(2 or 3 letters)Year(2digits)pointCode(4digits)))",
                "value": None,
                "description": "Unique name designating a single observation unit in time and space",
                "description_fr": "Nom unique désignant une seule unité d'observation dans le temps et l'espace",
                "acquisition_mode": "Field Sheet", "example": "CC190001", "ifdo_id": None
            },
            "video_file_name": {
                "name": "Video file name", "name_fr": "Nom du fichier vidéo", "type": "str",
                "format": "Text DateTime (YYYYMMDDhhmm) + region code + codeObs + extension",
                "value": None,
                "description": "Name of the video file",
                "description_fr": "Nom du fichier vidéo",
                "acquisition_mode": "System", "example": "20190626161037_MED_CB190004.m2ts", "ifdo_id": None
            },
            "time": {
                "name": "Time", "name_fr": "Heure", "type": "str",
                "format": "Texte (hh:mm)", "value": None,
                "description": "Local time of the start of the observation",
                "description_fr": "Heure locale de début de réalisation de l'observation",
                "acquisition_mode": "System", "example": "13:50", "ifdo_id": None
            },
            "latitude": {
                "name": "Latitude", "name_fr": "Latitude", "type": "float",
                "format": "Numérique (Degrés décimaux WGS 84)", "value": None,
                "description": "Geographical coordinate in decimal degrees",
                "description_fr": "Coordonnée géographique en degré décimal",
                "acquisition_mode": "System/Field Sheet", "example": "47.12345", "ifdo_id": None
            },
            "longitude": {
                "name": "Longitude", "name_fr": "Longitude", "type": "float",
                "format": "Numérique (Degrés décimaux WGS 84)", "value": None,
                "description": "Geographical coordinate in decimal degrees",
                "description_fr": "Coordonnée géographique en degré décimal",
                "acquisition_mode": "System/Field Sheet", "example": "-3.45678", "ifdo_id": None
            },
            "depth": {
                "name": "Depth", "name_fr": "Profondeur", "type": "float",
                "format": "Numérique (Mètres avec une décimale)", "value": None,
                "description": "Depth at which the video system is located",
                "description_fr": "Profondeur à laquelle se trouve le système vidéo",
                "acquisition_mode": "Sensor/Field Sheet", "example": "25.5", "ifdo_id": None
            },
            "moon": {
                "name": "Moon Phase", "name_fr": "Phase Lune", "type": "str",
                "format": "Texte", "value": None,
                "description": "Moon phase NM: New Moon, WC: Waxing Crescent, FQ: First Quarter, FM: Full Moon, LQ: Last Quarter",
                "description_fr": "Phase de la lune",
                "acquisition_mode": "Web API", "ifdo_id": None,
                "authorized_values_en": ["NM", "FQ", "FM", "LQ"],
                "authorized_values_fr": ["Nouvelle Lune", "Premier Croissant", "Premier Quartier", "Pleine Lune", "Dernier Quartier"]
            },
            "tide": {
                "name": "Tide", "name_fr": "Marée", "type": "str",
                "format": "Texte", "value": None,
                "description": "Tide stage", "description_fr": "Phase marée",
                "acquisition_mode": "Web API", "ifdo_id": None,
                "authorized_values_en": ["High", "Low", "Flooding", "Ebbing"],
                "authorized_values_fr": ["Haute", "Basse", "Inondation", "Embouchure"]
            },
            "coefficient": {
                "name": "Tide Coefficient", "name_fr": "Coefficient de marée", "type": "int",
                "format": "Numérique (Entier)", "value": None,
                "description": "Tide coefficient", "description_fr": "Coefficient de marée",
                "acquisition_mode": "Web API", "ifdo_id": None
            },
            "wind": {
                "name": "Wind Speed", "name_fr": "Vitesse du vent", "type": "int",
                "format": "Numérique (Échelle de Beaufort 0-12)", "value": None,
                "description": "Wind speed", "description_fr": "Vitesse du vent",
                "acquisition_mode": "Web API/Field Sheet", "ifdo_id": None,
                "authorized_values_en": list(range(13)),
                "authorized_values_fr": list(range(13))
            },
            "wind_direction": {
                "name": "Wind Direction", "name_fr": "Direction du vent", "type": "str",
                "format": "Alphanumérique", "value": None,
                "description": "Wind direction", "description_fr": "Direction du vent",
                "acquisition_mode": "Web API/Field Sheet", "ifdo_id": None,
                "authorized_values_en": ["N", "S", "E", "W", "NE", "NW", "SE", "SW"],
                "authorized_values_fr": ["N", "S", "E", "O", "NE", "NO", "SE", "So"]
            },
            "airTemp": {
                "name": "Air Temperature", "name_fr": "Température de l'air", "type": "float",
                "format": "Numérique (Celsius)", "value": None,
                "description": "Air temperature", "description_fr": "Température de l'air",
                "acquisition_mode": "Web API/Field Sheet", "ifdo_id": None
            },
            "seaState": {
                "name": "Sea State", "name_fr": "État de la mer", "type": "str",
                "format": "Alphanumérique (Échelle de Douglas)",
                "authorized_values_en": [str(i) for i in range(10)],
                "authorized_values_fr": [str(i) for i in range(10)],
                "value": None,
                "description": "Sea state (Douglas scale or similar)",
                "description_fr": "État de la mer",
                "acquisition_mode": "Web API, Field Sheet", "ifdo_id": None
            },
            "swell_height": {
                "name": "Swell Height", "name_fr": "Hauteur de la houle", "type": "str",
                "format": "Texte", "value": None,
                "description": "Swell height", "description_fr": "Hauteur de la houle",
                "acquisition_mode": "Web API, Field Sheet", "ifdo_id": None
            },
            "swell_direction": {
                "name": "Swell Direction", "name_fr": "Direction de la houle", "type": "str",
                "format": "Texte", "value": None,
                "description": "Swell direction", "description_fr": " Direction de la houle",
                "acquisition_mode": "Web API, Field Sheet", "ifdo_id": None
            },
            "point_name": {
                "name": "Point Name", "name_fr": "Nom du point", "type": "str",
                "format": "Alphanumérique", "value": None,
                "description": "Point name (usually last 4 digits of station code)",
                "description_fr": "Nom du point",
                "acquisition_mode": "Manual",
                "example": "4 derniers chiffres du codestation", "ifdo_id": None
            },
            "gps_waypoint": {
                "name": "GPS Waypoint", "name_fr": "Nom du point GPS", "type": "str",
                "format": "Alphanumérique", "value": None,
                "description": "Identification name of the observation in the GPS",
                "description_fr": "Nom d'identification de l'observation sur le GPS",
                "acquisition_mode": "GPS", "example": "101", "ifdo_id": None
            },
            "deployment_comment": {
                "name": "Deployment Comment", "name_fr": "Commentaire de pose", "type": "str",
                "format": "Texte", "value": None,
                "description": "Field notes regarding the camera deployment",
                "description_fr": "Commentaire relevé sur le terrain concernant la pose",
                "acquisition_mode": "IHM, Field Sheet", "example": "Libre", "ifdo_id": None
            },
            "water_temperature": {
                "name": "Water Temperature", "name_fr": "Température de l'eau", "type": "float",
                "format": "Numérique (Celsius)", "value": None,
                "description": "Water temperature during observation",
                "description_fr": "Température de l'eau",
                "acquisition_mode": "Sensor", "example": "17.1", "ifdo_id": None
            },
            "weather": {
                "name": "Weather", "name_fr": "Météo", "type": "str",
                "format": "Texte", "value": None,
                "description": "State of the sky (cloud cover, rain, etc.)",
                "description_fr": "Etat du ciel (nébulosité, pluie,…)",
                "acquisition_mode": "Field Sheet", "example": "Soleil, nuageux, pluie…", "ifdo_id": None
            },
            "exploitable": {
                "name": "Exploitable", "name_fr": "Exploitable", "type": "str",
                "format": "Texte", "value": "oui",
                "description": "Usability status of the video for analysis",
                "description_fr": "Exploitabilité de la vidéo",
                "acquisition_mode": "IHM", "example": "oui, non, habitat, ?", "ifdo_id": None,
                "authorized_values_fr": ["oui", "non", "habitat", "?", "communication"],
                "authorized_values_en": ["yes", "no", "habitat", "?", "communication"]
            },
            "estimated_visibility": {
                "name": "Estimated Visibility", "name_fr": "Visibilité Estimée", "type": "int",
                "format": "Numérique (Mètres)", "value": None,
                "description": "Estimated visibility in the video (in meters)",
                "description_fr": "Visibilité estimée sur la vidéo (en mètres)",
                "acquisition_mode": "IHM", "example": "5", "ifdo_id": None
            },
            "derusher": {
                "name": "Derusher", "name_fr": "Analyseur", "type": "str",
                "format": "Texte", "value": None,
                "description": "Name of the person derushing",
                "description_fr": "Nom de la personne qui derushe",
                "acquisition_mode": "IHM", "example": "Olivier Fauvarque", "ifdo_id": None
            },
            "events_deployment": [events_deployment_schema],
            "events_animal": [events_animal_schema],
            "events_interesting_images": [events_images_schema]
        }
    }


def _convert_date(old_date: str | None) -> str | None:
    """'2025-08-21' → '20250821'. Returns None on failure."""
    if not old_date:
        return None
    try:
        return old_date.replace("-", "")
    except Exception:
        return None


def _convert_time(hmsos: str | None) -> str | None:
    """'12:01:37' → '12:01'. Returns None on failure."""
    if not hmsos:
        return None
    parts = hmsos.split(":")
    if len(parts) >= 2:
        return f"{parts[0]}:{parts[1]}"
    return hmsos


def migrate_legacy_to_new(old_data: dict) -> dict:
    """Return a new-format dict with values mapped from *old_data*."""
    template = _build_base_template()
    sys_old = old_data.get("system", {})
    camp = old_data.get("campaign", {})
    vid = old_data.get("video", {})

    zone = camp.get("zoneDict", {})
    date_d = camp.get("dateDict", {})
    deploy = camp.get("deploiementDict", {})
    gps = vid.get("gpsDict", {})
    ctd = vid.get("ctdDict", {})
    astro = vid.get("astroDict", {})
    hour = vid.get("hourDict", {})
    meteo_air = vid.get("meteoAirDict", {})
    meteo_mer = vid.get("meteoMerDict", {})
    station = vid.get("stationDict", {})
    analyse = vid.get("analyseDict", {})

    # system
    s = template["system"]
    s["camera"]["value"] = sys_old.get("camera")
    s["model_mcu"]["value"] = sys_old.get("model")
    s["type_system"]["value"] = sys_old.get("system")
    s["system_version"]["value"] = sys_old.get("version")

    # survey
    sv = template["survey"]
    sv["region"]["value"] = zone.get("campaign")
    sv["zone"]["value"] = zone.get("zone")
    sv["site"]["value"] = zone.get("locality")
    sv["protectionStatus2"]["value"] = zone.get("protection")
    sv["date"]["value"] = _convert_date(date_d.get("date"))
    sv["boat_name"]["value"] = deploy.get("boat")
    sv["pilot_name"]["value"] = deploy.get("pilot")
    sv["crew_names"]["value"] = deploy.get("crew")

    # video_observation
    vo = template["video_observation"]
    lat = gps.get("latitude")
    lon = gps.get("longitude")
    vo["latitude"]["value"] = lat if lat not in (None, 0) else None
    vo["longitude"]["value"] = lon if lon not in (None, 0) else None
    vo["point_name"]["value"] = gps.get("site")
    vo["depth"]["value"] = ctd.get("depth")
    vo["water_temperature"]["value"] = ctd.get("temperature")
    vo["coefficient"]["value"] = astro.get("coefficient")
    vo["moon"]["value"] = astro.get("moon")
    vo["tide"]["value"] = astro.get("tide")
    vo["wind"]["value"] = meteo_air.get("wind")
    vo["wind_direction"]["value"] = meteo_air.get("direction")
    vo["weather"]["value"] = meteo_air.get("sky")
    vo["airTemp"]["value"] = meteo_air.get("tempAir")
    vo["seaState"]["value"] = meteo_mer.get("seaState")
    vo["swell_height"]["value"] = meteo_mer.get("swell")
    vo["codeObs"]["value"] = station.get("codestation")
    vo["time"]["value"] = _convert_time(hour.get("HMSOS"))
    vo["exploitable"]["value"] = analyse.get("exploitability") or "oui"
    vo["estimated_visibility"]["value"] = analyse.get("visibility")

    return template


def migrate_json_file_if_needed(json_path: str) -> bool:
    """Read *json_path*, migrate in place if legacy format. Returns True if migrated."""
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[MIGRATION] Cannot read {json_path}: {e}")
        return False

    if not is_legacy_format(data):
        return False

    print(f"[MIGRATION] Legacy JSON detected — converting: {json_path}")
    new_data = migrate_legacy_to_new(data)

    backup_path = json_path + ".legacy_backup"
    if not os.path.exists(backup_path):
        try:
            with open(backup_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[MIGRATION] Warning: could not write backup {backup_path}: {e}")

    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(new_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[MIGRATION] Cannot write migrated JSON {json_path}: {e}")
        return False

    return True
