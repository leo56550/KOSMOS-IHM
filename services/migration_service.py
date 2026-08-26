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


def _extract_raw_value(v):
    """Extrait la valeur scalaire d'un champ du JSON brut.

    Le JSON brut <stem>.json peut être soit à plat (system.camera = "imx477"),
    soit déjà au format riche (system.camera = {"value": "imx477", ...}) selon
    la version du système d'acquisition — on ne veut jamais imbriquer tout le
    dict riche dans le champ "value" du template.
    """
    if isinstance(v, dict) and "value" in v:
        return v.get("value")
    return v


# Anciens JSON bruts "system" à plat : noms de clés courts, différents du template.
_RAW_TO_TEMPLATE_SYSTEM = {
    "camera":  "camera",
    "model":   "model_mcu",
    "system":  "type_system",
    "version": "system_version",
}


def _merge_raw_block(temp_block: dict, raw_block: dict, legacy_key_map: dict | None = None,
                      only_if_empty: bool = False, exclude_keys: set | None = None) -> list:
    """Copie les valeurs non vides de raw_block dans temp_block pour les clés communes.

    Le JSON brut <stem>.json est aujourd'hui au même format riche que template.json,
    donc pour la plupart des champs (dont tout le bloc "survey") la clé est identique
    des deux côtés — une simple correspondance directe suffit. legacy_key_map ne sert
    que de repli pour d'anciens JSON "system" à plat avec des noms de clés différents.
    exclude_keys : clés jamais copiées depuis le brut, même si only_if_empty=False —
    pour les champs strictement décidés par l'IHM (ex. "exploitable") qu'un JSON brut
    ne doit jamais pouvoir écraser, peu importe ce qu'il contient.
    Retourne la liste des "clé = valeur" effectivement copiés (pour le log appelant).
    """
    if not isinstance(raw_block, dict) or not isinstance(temp_block, dict):
        return []
    changed = []
    for tmpl_key, entry in temp_block.items():
        if not isinstance(entry, dict) or "value" not in entry:
            continue
        if exclude_keys and tmpl_key in exclude_keys:
            continue
        if only_if_empty and entry.get("value"):
            continue
        val = _extract_raw_value(raw_block.get(tmpl_key))
        if val is None and legacy_key_map:
            raw_key = next((rk for rk, tk in legacy_key_map.items() if tk == tmpl_key), None)
            if raw_key:
                val = _extract_raw_value(raw_block.get(raw_key))
        if val is not None and val != "" and entry.get("value") != val:
            entry["value"] = val
            changed.append(f"{tmpl_key} = {val!r}")
    return changed


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

        # ── Auto-remplissage des champs dérivés du chemin ─────────────────
        import re as _re
        vo = data.get("video_observation", {})

        # video_path → "<campagne>\<système>"
        # Structure : campagne/système/numéro_vidéo/fichier.mp4
        # ex. "260611_ATL_CC_ENEZEG\260611_SVR_K53"
        system_folder = os.path.basename(os.path.dirname(folder))
        campaign_folder = os.path.basename(os.path.dirname(os.path.dirname(folder)))
        vpath_val = f"{campaign_folder}\\{system_folder}"
        if "video_path" in vo:
            vo["video_path"]["value"] = vpath_val

        # video_number → dernier bloc numérique du stem, zero-paddé sur 4 chiffres
        # ex. "0018" depuis "0018.mp4"
        digits = _re.findall(r'\d+', stem)
        if digits and "video_number" in vo:
            vo["video_number"]["value"] = digits[-1].zfill(4)

        # video_file_name → nom du fichier vidéo sans extension
        if "video_file_name" in vo:
            vo["video_file_name"]["value"] = stem

        # qualifiable → "yes" par défaut (vidéo retenue tant qu'elle n'est pas jetée)
        if "qualifiable" in vo:
            vo["qualifiable"]["value"] = "yes"

        # exploitable → "?" par défaut (statut pas encore déterminé, à distinguer d'un
        # champ simplement vide) — convention déjà utilisée partout dans l'IHM (badges,
        # couleurs de la liste vidéo, légende de la vue globale).
        if "exploitable" in vo:
            vo["exploitable"]["value"] = "?"

        # Pas de survey.datawork_folder / survey.video_subfolder : redondants avec
        # video_observation.video_path / video_number déjà remplis ci-dessus.

        # ── Champs system + survey depuis le JSON brut <stem>.json ────────
        raw_json_path = os.path.join(folder, f"{stem}.json")
        if os.path.isfile(raw_json_path):
            try:
                with open(raw_json_path, "r", encoding="utf-8") as f_raw:
                    raw = json.load(f_raw)
                mapped = []
                mapped += [f"system.{c}" for c in _merge_raw_block(
                    data.setdefault("system", {}), raw.get("system", {}),
                    legacy_key_map=_RAW_TO_TEMPLATE_SYSTEM)]
                mapped += [f"survey.{c}" for c in _merge_raw_block(
                    data.setdefault("survey", {}), raw.get("survey", {}))]
                # video_observation : ne copie que les champs déjà présents dans le template
                # (donc jamais les champs propres à l'IHM, absents du JSON brut d'acquisition) —
                # notamment "time" (heure RTC), nécessaire au nom de dossier d'export.
                # exploitable/qualifiable exclus : ce sont des décisions IHM (qualification/
                # validation), jamais des champs d'acquisition — un JSON brut qui contiendrait
                # une valeur (ex. un vieux "oui" résiduel) ne doit jamais les écraser.
                # point_name/station_number exclus aussi : ne doivent JAMAIS être auto-remplis
                # depuis le brut — uniquement saisis via l'ardoise en page Validation.
                mapped += [f"video_observation.{c}" for c in _merge_raw_block(
                    data.setdefault("video_observation", {}), raw.get("video_observation", {}),
                    exclude_keys={"exploitable", "qualifiable", "point_name", "station_number"})]
                if mapped:
                    print(f"[TEMP_JSON] {stem}_temp.json ← depuis {stem}.json :")
                    for entry in mapped:
                        print(f"            {entry}")
            except Exception as e_raw:
                print(f"[INIT] Impossible de lire {stem}.json pour system/survey/video_observation : {e_raw}")

        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[INIT] {stem}_temp.json créé"
              f" (video_path={vpath_val!r}, video_number={vo.get('video_number', {}).get('value')!r})")
        return True
    except Exception as e:
        print(f"[INIT] Impossible de créer {stem}_temp.json : {e}")
        return False


def update_temp_json_paths(video_path: str) -> None:
    """Met à jour les champs chemin dans un _temp.json existant si leurs valeurs sont nulles.

    Appelée à chaque ouverture de campagne pour garantir que video_path,
    video_number, video_file_name, datawork_folder et video_subfolder sont remplis.
    """
    import re as _re
    folder = os.path.dirname(os.path.normpath(video_path))
    stem = os.path.splitext(os.path.basename(video_path))[0]
    temp_path = os.path.join(folder, f"{stem}_temp.json")
    if not os.path.isfile(temp_path):
        return

    system_folder = os.path.basename(os.path.dirname(folder))
    campaign_folder = os.path.basename(os.path.dirname(os.path.dirname(folder)))
    vpath_val = f"{campaign_folder}\\{system_folder}"
    digits = _re.findall(r'\d+', stem)
    video_number_val = digits[-1].zfill(4) if digits else stem

    try:
        with open(temp_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        modified = False
        vo = data.get("video_observation", {})

        # Champs purement dérivés du chemin : toujours recalculés (jamais saisis manuellement)
        for field, value in (
            ("video_path",      vpath_val),
            ("video_number",    video_number_val),
            ("video_file_name", stem),
        ):
            if field in vo:
                entry = vo[field] if isinstance(vo[field], dict) else {}
                if entry.get("value") != value:
                    entry["value"] = value
                    vo[field] = entry
                    modified = True

        # exploitable → "?" si encore vide (anciens _temp.json créés avant l'ajout de ce
        # défaut) — ne touche jamais un statut déjà qualifié ("oui"/"non"/"?"/etc.).
        if "exploitable" in vo:
            entry = vo["exploitable"] if isinstance(vo["exploitable"], dict) else {}
            if not entry.get("value"):
                entry["value"] = "?"
                vo["exploitable"] = entry
                modified = True

        # Pas de survey.datawork_folder / survey.video_subfolder : redondants avec
        # video_observation.video_path / video_number déjà mis à jour ci-dessus.

        # Champs system + survey depuis le JSON brut (seulement si vides dans le temp,
        # pour ne jamais écraser une saisie manuelle déjà faite dans l'IHM)
        raw_json_path = os.path.join(folder, f"{stem}.json")
        if os.path.isfile(raw_json_path):
            try:
                with open(raw_json_path, "r", encoding="utf-8") as f_raw:
                    raw = json.load(f_raw)
                mapped = []
                sys_changed = _merge_raw_block(
                    data.setdefault("system", {}), raw.get("system", {}),
                    legacy_key_map=_RAW_TO_TEMPLATE_SYSTEM, only_if_empty=True)
                surv_changed = _merge_raw_block(
                    data.setdefault("survey", {}), raw.get("survey", {}), only_if_empty=True)
                # video_observation : idem, seulement les champs vides (ex. "time" — heure RTC —
                # nécessaire au nom de dossier d'export), ne touche jamais une saisie IHM existante.
                # exploitable/qualifiable toujours exclus (décisions IHM, jamais depuis le brut).
                # point_name/station_number exclus aussi : ne doivent JAMAIS être auto-remplis
                # depuis le brut — uniquement saisis via l'ardoise en page Validation.
                vob_changed = _merge_raw_block(
                    data.setdefault("video_observation", {}), raw.get("video_observation", {}),
                    only_if_empty=True,
                    exclude_keys={"exploitable", "qualifiable", "point_name", "station_number"})
                if sys_changed or surv_changed or vob_changed:
                    modified = True
                mapped += [f"system.{c}" for c in sys_changed]
                mapped += [f"survey.{c}" for c in surv_changed]
                mapped += [f"video_observation.{c}" for c in vob_changed]
                if mapped:
                    print(f"[TEMP_JSON] {stem}_temp.json ← depuis {stem}.json :")
                    for entry in mapped:
                        print(f"            {entry}")
            except Exception:
                pass

        if modified:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[UPDATE_PATHS] {stem}_temp.json : {e}")


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

    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(new_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[MIGRATION] Cannot write migrated JSON {json_path}: {e}")
        return False

    return True
