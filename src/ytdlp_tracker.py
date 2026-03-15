"""Track daily yt-dlp call count in a machine-wide JSON file."""

import json
import os
import threading
from datetime import date

from src.config import get_transcription_config

_DATA_DIR = os.path.join(
    os.environ.get('XDG_DATA_HOME', os.path.expanduser('~/.local/share')),
    'tubedigest',
)
_USAGE_PATH = os.path.join(_DATA_DIR, 'ytdlp_usage.json')
_lock = threading.Lock()


def _today() -> str:
    return date.today().isoformat()


def _read() -> dict:
    try:
        with open(_USAGE_PATH) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    # Reset if date changed
    if data.get('date') != _today():
        data = {'date': _today(), 'ytdlp_count': 0}
    return data


def _write(data: dict) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_USAGE_PATH, 'w') as f:
        json.dump(data, f)


def get_ytdlp_count() -> int:
    """Return today's yt-dlp call count."""
    with _lock:
        return _read()['ytdlp_count']


def increment_ytdlp_count() -> int:
    """Increment and return the new yt-dlp call count."""
    with _lock:
        data = _read()
        data['ytdlp_count'] += 1
        _write(data)
        return data['ytdlp_count']


def check_ytdlp_limit() -> bool:
    """Return True if the daily yt-dlp limit has been reached."""
    cfg = get_transcription_config()
    limit = cfg.get('ytdlp_daily_limit', 50)
    return get_ytdlp_count() >= limit
