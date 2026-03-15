"""Playlist URL detection and video list extraction."""

import logging
import re

from src.config import get_transcription_config
from src.fetcher import extract_video_id
from src.ytdlp_tracker import check_ytdlp_limit, increment_ytdlp_count

log = logging.getLogger(__name__)

PLAYLIST_PATTERNS = [
    re.compile(r'[?&]list=([a-zA-Z0-9_-]+)'),
    re.compile(r'(?:https?://)?(?:www\.)?youtube\.com/playlist\?list=([a-zA-Z0-9_-]+)'),
]


def is_playlist_url(url: str) -> bool:
    """Check if a URL contains a YouTube playlist."""
    return any(p.search(url) for p in PLAYLIST_PATTERNS)


def _extract_pytubefix(url: str) -> dict:
    from pytubefix import Playlist
    p = Playlist(url)
    videos = []
    for video in p.videos:
        vid = extract_video_id(video.watch_url) or video.video_id
        videos.append({
            'video_id': vid,
            'title': video.title or 'Unknown Title',
        })
    return {
        'title': p.title or 'Unknown Playlist',
        'videos': videos,
    }


def _extract_ytdlp(url: str) -> dict:
    if check_ytdlp_limit():
        raise RuntimeError("yt-dlp daily limit reached")
    import yt_dlp
    opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'skip_download': True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    increment_ytdlp_count()

    videos = []
    for entry in info.get('entries', []):
        if entry is None:
            continue
        video_id = entry.get('id') or entry.get('url')
        if video_id:
            videos.append({
                'video_id': video_id,
                'title': entry.get('title', 'Unknown Title'),
            })

    return {
        'title': info.get('title', 'Unknown Playlist'),
        'videos': videos,
    }


_PLAYLIST_BACKENDS = {
    'pytubefix': _extract_pytubefix,
    'ytdlp': _extract_ytdlp,
}


def extract_playlist_videos(url: str) -> dict:
    """Extract video IDs and metadata from a playlist URL.

    Tries backends in config order (video_backend setting).

    Returns:
        {
            'title': 'Playlist Name',
            'videos': [{'video_id': '...', 'title': '...'}, ...]
        }
    """
    backends = get_transcription_config().get('video_backend', ['pytubefix', 'ytdlp'])
    errors = []
    for name in backends:
        fn = _PLAYLIST_BACKENDS.get(name)
        if not fn:
            continue
        try:
            result = fn(url)
            log.info("Playlist extracted via %s: \"%s\" (%d videos)", name, result['title'], len(result['videos']))
            return result
        except Exception as e:
            log.warning("Playlist extraction failed with %s: %s", name, e)
            errors.append(f"{name}: {e}")

    raise RuntimeError(
        f"All playlist backends failed for {url}:\n" +
        "\n".join(f"  - {err}" for err in errors)
    )
