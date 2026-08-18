"""Converts legacy template.json (v3-style flat dicts) to the current rich-field format."""

import json
import os
import shutil


def is_legacy_format(data: dict) -> bool:
    """Return True if *data* uses the old flat dict structure (pre-v4 rich fields)."""
    if not isinstance(data, dict):
        return False
    video = data.get("video", {})
    return isinstance(video, dict) and "gpsDict" in video


def _build_base_template() -> dict:
    """Lit template.json (source unique de vérité) et le retourne comme base pour les vidéos."""
    template_path = os.path.join(os.path.dirname(__file__), "..", "template.json")
    with open(template_path, "r", encoding="utf-8") as f:
        return json.load(f)


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
    sv["date"]["value"] = _convert_date(date_d.get("date"))
    sv["boat_name"]["value"] = deploy.get("boat")
    sv["pilot_name"]["value"] = deploy.get("pilot")
    sv["crew_names"]["value"] = deploy.get("crew")

    # video_observation
    vo = template["video_observation"]
    # site/protectionStatus sont dans video_observation dans le nouveau template
    if "site" in vo:
        vo["site"]["value"] = zone.get("locality")
    if "protectionStatus2" in vo:
        vo["protectionStatus2"]["value"] = zone.get("protection")
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
    vo["exploitable"]["value"] = analyse.get("exploitability") or "?"
    vo["estimated_visibility"]["value"] = analyse.get("visibility")

    return template


def initialise_video_json_if_needed(video_path: str) -> bool:
    """Copy template.json → <stem>.json if the stem JSON doesn't exist yet.

    Called once per video at campaign opening.  After this call,
    get_video_json_path(video_path) is guaranteed to exist (if template.json was present).
    Returns True if a copy was made.
    """
    folder = os.path.dirname(os.path.normpath(video_path))
    stem = os.path.splitext(os.path.basename(video_path))[0]
    target = os.path.join(folder, f"{stem}.json")

    if os.path.isfile(target):
        return False  # already initialised

    template = os.path.join(folder, "template.json")
    if not os.path.isfile(template):
        return False  # nothing to copy

    try:
        shutil.copy2(template, target)
        print(f"[INIT] {stem}.json créé depuis template.json")
        # Forcer exploitable à "?" — la valeur héritée du template peut être "oui"
        with open(target, 'r', encoding='utf-8') as f:
            data = json.load(f)
        vo = data.setdefault("video_observation", {})
        expl = vo.setdefault("exploitable", {})
        expl["value"] = "?"
        with open(target, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[INIT] Impossible de créer {stem}.json : {e}")
        return False


def _nullify_values(node) -> None:
    """Met récursivement à null tous les champs 'value' d'un arbre JSON."""
    if isinstance(node, dict):
        if "value" in node:
            node["value"] = None
        for v in node.values():
            _nullify_values(v)
    elif isinstance(node, list):
        for item in node:
            _nullify_values(item)


def initialise_temp_json_if_needed(video_path: str) -> bool:
    """Crée <stem>_temp.json dans le dossier brut si absent.

    Basé sur le template.json de l'application (dossier racine du projet),
    toutes les valeurs 'value' sont mises à null — l'IHM les complète progressivement.
    Ne touche jamais à <stem>.json (données d'acquisition brutes).
    Retourne True si le fichier a été créé.
    """
    folder = os.path.dirname(os.path.normpath(video_path))
    stem = os.path.splitext(os.path.basename(video_path))[0]
    temp_path = os.path.join(folder, f"{stem}_temp.json")
    if os.path.isfile(temp_path):
        return False  # déjà initialisé

    # template.json de l'application (dossier racine, pas du dossier vidéo)
    app_template = os.path.join(os.path.dirname(__file__), "..", "template.json")
    if not os.path.isfile(app_template):
        print(f"[INIT] template.json introuvable : {app_template}")
        return False

    try:
        with open(app_template, "r", encoding="utf-8") as f:
            data = json.load(f)
        _nullify_values(data)
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[INIT] {stem}_temp.json créé (valeurs nulles)")
        return True
    except Exception as e:
        print(f"[INIT] Impossible de créer {stem}_temp.json : {e}")
        return False


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
