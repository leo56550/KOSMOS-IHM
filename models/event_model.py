import csv
import json
import os
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Event:
    """Représente un événement annoté sur la timeline."""
    event_id: str
    label: str
    frame_start: int
    frame_end: int
    fps: float
    color: str = "#2778a2"
    category: str = "events_deployment"
    description: str = ""

    @property
    def start_ms(self) -> int:
        return int((self.frame_start / self.fps) * 1000) if self.fps > 0 else 0

    @property
    def end_ms(self) -> int:
        return int((self.frame_end / self.fps) * 1000) if self.fps > 0 else 0

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "value": self.label,
            "frame_number_start": self.frame_start,
            "frame_number_end": self.frame_end,
            "color": self.color,
            "description": self.description,
        }


class EventModel:
    """Gère la liste des événements, la persistance JSON et l'export CSV.

    Pas un QAbstractItemModel : les données sont exposées via la propriété `events`
    et les vues sont notifiées via des callbacks ou des signaux du contrôleur.
    """

    def __init__(self):
        """Initialise la liste d'événements, le chemin JSON et le FPS par défaut."""
        self._events: List[Event] = []
        self._json_path: Optional[str] = None
        self._fps: float = 25.0

    # ------------------------------------------------------------------
    # Propriétés
    # ------------------------------------------------------------------

    @property
    def events(self) -> List[Event]:
        return list(self._events)

    @property
    def fps(self) -> float:
        return self._fps

    @fps.setter
    def fps(self, value: float):
        self._fps = value if value > 0 else 25.0

    @property
    def json_path(self) -> Optional[str]:
        return self._json_path

    # ------------------------------------------------------------------
    # Chargement / Sauvegarde JSON
    # ------------------------------------------------------------------

    def load_from_json(self, json_path: str, category: str = "events_deployment"):
        """Charge les événements depuis un template.json."""
        self._json_path = json_path
        self._events = []

        if not os.path.isfile(json_path):
            return

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            video_obs = data.get("video_observation", {})
            categories = ["events_deployment", "events_interesting_images", "events_animal"]

            for cat in categories:
                if cat not in video_obs:
                    continue
                cat_data = video_obs[cat]
                if not isinstance(cat_data, list) or not cat_data:
                    continue
                values_list = cat_data[0].get("values", [])

                for ev in values_list:
                    event = Event(
                        event_id=ev.get("event_id", ""),
                        label=str(ev.get("value", "")),
                        frame_start=int(ev.get("frame_number_start", 0)),
                        frame_end=int(ev.get("frame_number_end", 0)),
                        fps=self._fps,
                        color=ev.get("color", "#2778a2"),
                        category=cat,
                        description=ev.get("description", ""),
                    )
                    self._events.append(event)

        except Exception as e:
            print(f"[EventModel] Erreur chargement JSON : {e}")

    def save_event(self, event: Event):
        """Ajoute ou met à jour un événement dans le JSON."""
        if not self._json_path:
            return

        existing = next((e for e in self._events if e.event_id == event.event_id), None)
        if existing:
            self._events.remove(existing)
        self._events.append(event)

        self._write_events_to_json()

    def delete_event(self, event_id: str):
        """Supprime un événement par son ID."""
        self._events = [e for e in self._events if e.event_id != event_id]
        self._write_events_to_json()

    def _write_events_to_json(self):
        """Réécrit tous les événements dans le template.json."""
        if not self._json_path or not os.path.isfile(self._json_path):
            return

        try:
            with open(self._json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            video_obs = data.setdefault("video_observation", {})

            categories = ["events_deployment", "events_interesting_images", "events_animal"]
            for cat in categories:
                events_in_cat = [e.to_dict() for e in self._events if e.category == cat]
                if cat not in video_obs or not isinstance(video_obs[cat], list):
                    video_obs[cat] = [{"values": []}]
                video_obs[cat][0]["values"] = events_in_cat

            with open(self._json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

        except Exception as e:
            print(f"[EventModel] Erreur écriture JSON : {e}")

    # ------------------------------------------------------------------
    # Export CSV
    # ------------------------------------------------------------------

    def export_csv(self, output_path: str):
        """Exporte les événements au format CSV VIAME-compatible."""
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow([
                    "# 1: Detection or Track-id",
                    "2: Video or Image Identifier",
                    "3: Unique Frame Identifier",
                    "4-7: Img-bbox(TL_x",
                    "TL_y",
                    "BR_x",
                    "BR_y)",
                    "8: Detection or Length Confidence",
                    "9: Target Length (meters)",
                    "10+: Repeated Species"
                ])
                for event in self._events:
                    writer.writerow([
                        event.event_id,
                        "",
                        event.frame_start,
                        0, 0, 0, 0,
                        1.0,
                        -1,
                        event.label, 1.0
                    ])
        except Exception as e:
            print(f"[EventModel] Erreur export CSV : {e}")
