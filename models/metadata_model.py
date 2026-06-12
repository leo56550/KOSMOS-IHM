import json
import os


class MetadataModel:
    """Modèle des métadonnées d'une vidéo : chargement, mise à jour et persistance JSON."""

    WEATHER_SEA_KEYS = [
        "moon", "tide", "coefficient", "wind", "wind_direction",
        "airTemp", "seaState", "swell_height", "swell_direction",
        "water_temperature", "weather"
    ]

    def __init__(self):
        self._json_data: dict = {}
        self._json_path: str = ""

    @property
    def json_path(self) -> str:
        return self._json_path

    @property
    def data(self) -> dict:
        return self._json_data

    # ------------------------------------------------------------------
    # Chargement
    # ------------------------------------------------------------------

    def load(self, json_path: str):
        """Charge toutes les métadonnées depuis un template.json."""
        if not os.path.isfile(json_path):
            print(f"[MetadataModel] JSON introuvable : {json_path}")
            return False

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                self._json_data = json.load(f)
            self._json_path = json_path
            return True
        except Exception as e:
            print(f"[MetadataModel] Erreur lecture : {e}")
            return False

    def reload(self):
        """Recharge depuis le fichier courant."""
        if self._json_path:
            self.load(self._json_path)

    # ------------------------------------------------------------------
    # Accès aux données
    # ------------------------------------------------------------------

    def get_block(self, block_key: str) -> dict:
        return self._json_data.get(block_key, {})

    def get_weather_sea_data(self) -> dict:
        """Retourne uniquement les champs météo/mer depuis video_observation."""
        video_obs = self._json_data.get("video_observation", {})
        return {k: v for k, v in video_obs.items() if k in self.WEATHER_SEA_KEYS}

    def get_specific_video_data(self) -> dict:
        """Retourne les champs vidéo spécifiques (hors météo/mer)."""
        video_obs = self._json_data.get("video_observation", {})
        return {k: v for k, v in video_obs.items() if k not in self.WEATHER_SEA_KEYS}

    # ------------------------------------------------------------------
    # Mise à jour et persistance
    # ------------------------------------------------------------------

    def update_field(self, block_key: str, field_id: str, new_value: str):
        """Met à jour un champ en mémoire et sauvegarde sur disque."""
        if block_key in self._json_data and field_id in self._json_data[block_key]:
            self._json_data[block_key][field_id]["value"] = new_value

        self._save_to_file(self._json_path)

    def update_field_all_videos(self, block_key: str, field_id: str, new_value: str,
                                 video_paths: list):
        """Propage une mise à jour de champ à tous les template.json de la campagne.

        Utilisé pour les blocs 'system' et 'survey' communs à toutes les vidéos.
        """
        for video_path in video_paths:
            if not os.path.exists(video_path):
                continue
            json_video_path = os.path.join(os.path.dirname(video_path), "template.json")
            if not os.path.exists(json_video_path):
                continue
            try:
                with open(json_video_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if block_key in data and field_id in data[block_key]:
                    data[block_key][field_id]["value"] = new_value
                    self._save_to_file(json_video_path, data)
            except Exception as e:
                print(f"[MetadataModel] Erreur sync {json_video_path} : {e}")

    def _save_to_file(self, path: str, data: dict = None):
        if data is None:
            data = self._json_data
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[MetadataModel] Erreur écriture {path} : {e}")

    def save(self):
        """Sauvegarde l'état courant dans le fichier JSON actif."""
        self._save_to_file(self._json_path)
