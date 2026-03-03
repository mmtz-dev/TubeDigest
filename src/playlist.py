"""Playlist URL detection and video list extraction."""

import re

import yt_dlp


PLAYLIST_PATTERNS = [
    re.compile(r'[?&]list=([a-zA-Z0-9_-]+)'),
    re.compile(r'(?:https?://)?(?:www\.)?youtube\.com/playlist\?list=([a-zA-Z0-9_-]+)'),
]


def is_playlist_url(url: str) -> bool:
    """Check if a URL contains a YouTube playlist."""
    return any(p.search(url) for p in PLAYLIST_PATTERNS)


def extract_playlist_videos(url: str) -> dict:
    """Extract video IDs and metadata from a playlist URL using yt-dlp flat extraction.

    Returns:
        {
            'title': 'Playlist Name',
            'videos': [{'video_id': '...', 'title': '...'}, ...]
        }
    """
    opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'skip_download': True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    playlist_title = info.get('title', 'Unknown Playlist')
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
        'title': playlist_title,
        'videos': videos,
    }
