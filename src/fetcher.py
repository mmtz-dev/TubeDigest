"""Video ID extraction, transcript + metadata fetching."""

import re
import time

import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi


YOUTUBE_URL_PATTERNS = [
    re.compile(r'(?:https?://)?(?:www\.)?youtube\.com/watch\?.*v=([a-zA-Z0-9_-]{11})'),
    re.compile(r'(?:https?://)?youtu\.be/([a-zA-Z0-9_-]{11})'),
    re.compile(r'(?:https?://)?(?:www\.)?youtube\.com/embed/([a-zA-Z0-9_-]{11})'),
    re.compile(r'(?:https?://)?(?:www\.)?youtube\.com/shorts/([a-zA-Z0-9_-]{11})'),
]


def extract_video_id(url: str) -> str | None:
    """Extract the 11-character video ID from a YouTube URL."""
    url = url.strip()
    for pattern in YOUTUBE_URL_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    # Bare video ID
    if re.fullmatch(r'[a-zA-Z0-9_-]{11}', url):
        return url
    return None


def fetch_video_metadata(video_id: str) -> dict:
    """Fetch video title and channel using yt-dlp (no download)."""
    url = f'https://www.youtube.com/watch?v={video_id}'
    opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': False,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return {
        'title': info.get('title', 'Unknown Title'),
        'channel': info.get('channel', info.get('uploader', 'Unknown Channel')),
        'duration': info.get('duration'),
    }


def fetch_transcript(video_id: str, include_timestamps: bool = True) -> list[dict]:
    """Fetch transcript for a video. Returns list of {text, start, duration} dicts.

    Retries once after 30s on rate-limit errors.
    """
    for attempt in range(2):
        try:
            ytt_api = YouTubeTranscriptApi()
            transcript = ytt_api.fetch(video_id)
            return [
                {
                    'text': snippet.text,
                    'start': snippet.start,
                    'duration': snippet.duration,
                }
                for snippet in transcript.snippets
            ]
        except Exception as e:
            error_msg = str(e).lower()
            is_rate_limit = any(
                term in error_msg
                for term in ['rate', 'limit', '429', 'too many']
            )
            if is_rate_limit and attempt == 0:
                time.sleep(30)
                continue
            raise
