"""Load and cache transcription config from config.yaml."""

import copy
import os

import yaml

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.yaml')

DEFAULTS = {
    'transcription': {
        'video_backend': ['pytubefix', 'ytdlp'],
        'short_max_minutes': 10,
        'mid_max_minutes': 20,
        'short_methods': ['whisper'],
        'mid_methods': ['pytubefix_subtitles', 'youtube_transcript_api', 'whisper'],
        'long_methods': ['youtube_transcript_api', 'pytubefix_subtitles', 'whisper'],
        'yt_api_daily_limit': 10,
        'ytdlp_daily_limit': 50,
        'whisper_enabled': True,
        'whisper_model': 'base',
        'whisper_device': 'auto',
        'subtitle_langs': ['en', 'en-US', 'en-GB'],
    },
    'summarization': {
        'providers': ['claude_cli', 'claude_proxy', 'gemini', 'ollama'],
        'gemini_model': 'gemini-2.0-flash',
        'ollama_model': 'llama3.1',
        'ollama_url': 'http://localhost:11434',
        'claude_proxy_url': 'http://host.docker.internal:9100',
        'prompt': (
            'Summarize the following YouTube video transcript concisely. '
            'Highlight the main topics, key points, and any conclusions or '
            'takeaways. Use clear headings and bullet points where appropriate.'
        ),
    },
}

_cached: dict | None = None


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = copy.deepcopy(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


def load_config(force_reload: bool = False) -> dict:
    """Load config from YAML, deep-merged with defaults. Cached after first call."""
    global _cached
    if _cached is not None and not force_reload:
        return _cached

    user_cfg = {}
    if os.path.exists(_CONFIG_PATH):
        with open(_CONFIG_PATH) as f:
            user_cfg = yaml.safe_load(f) or {}

    _cached = _deep_merge(DEFAULTS, user_cfg)
    return _cached


def get_transcription_config() -> dict:
    """Shortcut to get the transcription section."""
    return load_config()['transcription']


def get_summarization_config() -> dict:
    """Shortcut to get the summarization section."""
    return load_config()['summarization']
