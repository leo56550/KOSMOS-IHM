import json
import os
from datetime import datetime

_RECENTS_FILE = os.path.join(os.path.expanduser("~"), ".kosmos_ihm_recents.json")
MAX_RECENTS = 10


def load_recents() -> list[dict]:
    if not os.path.isfile(_RECENTS_FILE):
        return []
    try:
        with open(_RECENTS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_recents(recents: list[dict]) -> None:
    try:
        with open(_RECENTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(recents, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def add_recent_campaign(campaign_folder: str, working_dir: str,
                         campaign_name: str, derusher_name: str) -> None:
    recents = load_recents()
    recents = [r for r in recents if r.get('campaign_folder') != campaign_folder]
    recents.insert(0, {
        'campaign_folder': campaign_folder,
        'working_dir': working_dir or '',
        'campaign_name': campaign_name,
        'derusher_name': derusher_name,
        'last_opened': datetime.now().isoformat(timespec='seconds'),
    })
    _save_recents(recents[:MAX_RECENTS])


def remove_recent_campaign(campaign_folder: str) -> None:
    recents = load_recents()
    recents = [r for r in recents if r.get('campaign_folder') != campaign_folder]
    _save_recents(recents)
