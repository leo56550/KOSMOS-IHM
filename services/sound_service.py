"""Service de notifications sonores de l'IHM (fin d'export, ardoise saisie, ouverture campagne)."""

import os
import sys

from PyQt6.QtCore import QUrl
from PyQt6.QtMultimedia import QSoundEffect

_SOUND_FILES = {
    "export_complete": "export_complete.wav",
    "ardoise":          "ardoise.wav",
    "campaign_open":    "campaign_open.wav",
    "keep":             "keep.wav",
    "discard":          "discard.wav",
}


def _sounds_dir() -> str:
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.dirname(__file__))
    return os.path.join(base, "assets", "sounds")


class SoundService:
    """Charge et joue les effets sonores courts de l'IHM. Instance unique (voir get_sound_service)."""

    def __init__(self):
        self._effects: dict[str, QSoundEffect] = {}
        self._enabled = True
        sounds_dir = _sounds_dir()
        for name, filename in _SOUND_FILES.items():
            path = os.path.join(sounds_dir, filename)
            if not os.path.isfile(path):
                continue
            effect = QSoundEffect()
            effect.setSource(QUrl.fromLocalFile(path))
            effect.setVolume(0.5)
            self._effects[name] = effect

    def set_enabled(self, enabled: bool):
        self._enabled = enabled

    def play(self, name: str):
        if not self._enabled:
            return
        effect = self._effects.get(name)
        if effect is not None:
            effect.play()


_instance: SoundService | None = None


def get_sound_service() -> SoundService:
    global _instance
    if _instance is None:
        _instance = SoundService()
    return _instance
