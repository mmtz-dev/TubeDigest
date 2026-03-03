"""Track daily youtube-transcript-api call count in .usage.json."""

import json
import os
import threading
from datetime import date

_USAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.usage.json')
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
        data = {'date': _today(), 'yt_api_count': 0}
    return data


def _write(data: dict) -> None:
    with open(_USAGE_PATH, 'w') as f:
        json.dump(data, f)


def get_yt_api_count() -> int:
    """Return today's youtube-transcript-api call count."""
    with _lock:
        return _read()['yt_api_count']


def increment_yt_api_count() -> int:
    """Increment and return the new youtube-transcript-api call count."""
    with _lock:
        data = _read()
        data['yt_api_count'] += 1
        _write(data)
        return data['yt_api_count']
