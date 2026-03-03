"""Video ID extraction, transcript + metadata fetching."""

import json
import logging
import os
import re
import tempfile
import time

import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi

from src.config import get_transcription_config
from src.usage_tracker import get_yt_api_count, increment_yt_api_count

log = logging.getLogger(__name__)

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
    log.info("Fetching metadata for video: %s", video_id)
    url = f'https://www.youtube.com/watch?v={video_id}'
    opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': False,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    meta = {
        'title': info.get('title', 'Unknown Title'),
        'channel': info.get('channel', info.get('uploader', 'Unknown Channel')),
        'duration': info.get('duration'),
    }
    log.info("Metadata OK: \"%s\" by %s (duration=%s)", meta['title'], meta['channel'], meta['duration'])
    return meta


def fetch_transcript(video_id: str, include_timestamps: bool = True) -> list[dict]:
    """Fetch transcript via youtube-transcript-api. Returns list of {text, start, duration} dicts.

    Retries once after 30s on rate-limit errors.
    """
    for attempt in range(2):
        try:
            log.info("Fetching transcript for video: %s (attempt %d/2)", video_id, attempt + 1)
            ytt_api = YouTubeTranscriptApi()
            transcript = ytt_api.fetch(video_id)
            snippets = [
                {
                    'text': snippet.text,
                    'start': snippet.start,
                    'duration': snippet.duration,
                }
                for snippet in transcript.snippets
            ]
            log.info("Transcript OK: %d snippets fetched for %s", len(snippets), video_id)
            increment_yt_api_count()
            return snippets
        except Exception as e:
            log.warning("Transcript fetch failed for %s: %s", video_id, e)
            error_msg = str(e).lower()
            is_rate_limit = any(
                term in error_msg
                for term in ['rate', 'limit', '429', 'too many']
            )
            if is_rate_limit and attempt == 0:
                log.warning("Rate limited — waiting 30s before retry")
                time.sleep(30)
                continue
            raise


def fetch_transcript_ytdlp(video_id: str) -> list[dict]:
    """Fetch subtitles via yt-dlp in json3 format. Returns list of {text, start, duration} dicts."""
    cfg = get_transcription_config()
    langs = cfg['subtitle_langs']
    url = f'https://www.youtube.com/watch?v={video_id}'

    with tempfile.TemporaryDirectory() as tmpdir:
        outtmpl = os.path.join(tmpdir, '%(id)s.%(ext)s')
        opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': langs,
            'subtitlesformat': 'json3',
            'outtmpl': outtmpl,
        }

        log.info("Fetching subtitles via yt-dlp for %s (langs=%s)", video_id, langs)
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        # Find the downloaded subtitle file
        sub_file = None
        for fname in os.listdir(tmpdir):
            if fname.endswith('.json3'):
                sub_file = os.path.join(tmpdir, fname)
                break

        if not sub_file:
            raise RuntimeError(f"No subtitles found for {video_id} in languages {langs}")

        with open(sub_file) as f:
            data = json.load(f)

        snippets = []
        for event in data.get('events', []):
            # json3 events have tStartMs and dDurationMs
            start_ms = event.get('tStartMs', 0)
            duration_ms = event.get('dDurationMs', 0)
            segs = event.get('segs')
            if not segs:
                continue
            text = ''.join(seg.get('utf8', '') for seg in segs).strip()
            if not text or text == '\n':
                continue
            snippets.append({
                'text': text,
                'start': start_ms / 1000.0,
                'duration': duration_ms / 1000.0,
            })

        if not snippets:
            raise RuntimeError(f"yt-dlp subtitles were empty for {video_id}")

        log.info("yt-dlp subtitles OK: %d snippets for %s", len(snippets), video_id)
        return snippets


def fetch_transcript_whisper(video_id: str, emit_fn=None) -> list[dict]:
    """Download audio via yt-dlp, transcribe with local Whisper. Returns list of {text, start, duration} dicts."""
    cfg = get_transcription_config()
    if not cfg['whisper_enabled']:
        raise RuntimeError("Whisper is disabled in config.yaml")

    model_name = cfg['whisper_model']
    device_setting = cfg['whisper_device']

    # Lazy import to avoid slow load when unused
    import whisper
    import torch

    # Resolve device
    if device_setting == 'auto':
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
    else:
        device = device_setting

    if emit_fn:
        emit_fn('status', message=f'Loading Whisper model "{model_name}" on {device}...')
    log.info("Loading Whisper model '%s' on device '%s'", model_name, device)
    model = whisper.load_model(model_name, device=device)

    url = f'https://www.youtube.com/watch?v={video_id}'

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = os.path.join(tmpdir, 'audio.m4a')
        opts = {
            'quiet': True,
            'no_warnings': True,
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'outtmpl': audio_path,
        }

        if emit_fn:
            emit_fn('status', message=f'Downloading audio for Whisper transcription...')
        log.info("Downloading audio for %s", video_id)
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        if not os.path.exists(audio_path):
            # yt-dlp may have added a different extension
            for fname in os.listdir(tmpdir):
                audio_path = os.path.join(tmpdir, fname)
                break

        if emit_fn:
            emit_fn('status', message=f'Transcribing with Whisper ({model_name}/{device})... this may take a while.')
        log.info("Transcribing %s with Whisper", video_id)
        result = model.transcribe(audio_path)

        snippets = []
        for seg in result.get('segments', []):
            snippets.append({
                'text': seg['text'].strip(),
                'start': seg['start'],
                'duration': seg['end'] - seg['start'],
            })

        log.info("Whisper OK: %d segments for %s", len(snippets), video_id)
        return snippets


# Map method names to callables
_METHOD_MAP = {
    'youtube_transcript_api': lambda vid, ts, emit: fetch_transcript(vid, ts),
    'ytdlp_subtitles': lambda vid, ts, emit: fetch_transcript_ytdlp(vid),
    'whisper': lambda vid, ts, emit: fetch_transcript_whisper(vid, emit_fn=emit),
}


def fetch_transcript_auto(
    video_id: str,
    duration_seconds: int | None,
    include_timestamps: bool = True,
    emit_fn=None,
) -> tuple[list[dict], str]:
    """Orchestrate transcript fetching with daily gate and duration-based routing.

    Returns (transcript_snippets, method_name) tuple.
    """
    cfg = get_transcription_config()
    daily_limit = cfg['yt_api_daily_limit']
    short_max = cfg['short_max_minutes'] * 60
    mid_max = cfg['mid_max_minutes'] * 60

    # Daily gate: if under limit, try youtube_transcript_api first
    if get_yt_api_count() < daily_limit:
        methods = ['youtube_transcript_api', 'ytdlp_subtitles']
        if cfg['whisper_enabled']:
            methods.append('whisper')
        log.info("Under daily YT API limit — using youtube_transcript_api first for %s", video_id)
    else:
        # Duration-based routing
        if duration_seconds is not None and duration_seconds <= short_max:
            methods = list(cfg['short_methods'])
            tier = 'short'
        elif duration_seconds is not None and duration_seconds <= mid_max:
            methods = list(cfg['mid_methods'])
            tier = 'mid'
        else:
            methods = list(cfg['long_methods'])
            tier = 'long'
        log.info("Duration-based routing for %s: tier=%s, methods=%s", video_id, tier, methods)

    # Try each method in order
    errors = []
    yt_api_failed = False
    ytdlp_failed = False

    for method_name in methods:
        fn = _METHOD_MAP.get(method_name)
        if not fn:
            log.warning("Unknown transcription method: %s", method_name)
            continue

        if method_name == 'whisper' and not cfg['whisper_enabled']:
            log.info("Skipping whisper (disabled in config)")
            continue

        # Emit warning before Whisper fallback if both other methods failed
        if method_name == 'whisper' and yt_api_failed and ytdlp_failed and emit_fn:
            emit_fn(
                'warning',
                message='Both youtube-transcript-api and yt-dlp failed. '
                        'Falling back to Whisper (local transcription, this may be slow)...',
            )

        try:
            if emit_fn:
                emit_fn('status', message=f'Trying {method_name} for transcript...')
            transcript = fn(video_id, include_timestamps, emit_fn)
            log.info("Method %s succeeded for %s", method_name, video_id)
            return transcript, method_name
        except Exception as e:
            log.warning("Method %s failed for %s: %s", method_name, video_id, e)
            errors.append(f"{method_name}: {e}")
            if method_name == 'youtube_transcript_api':
                yt_api_failed = True
            elif method_name == 'ytdlp_subtitles':
                ytdlp_failed = True

    raise RuntimeError(
        f"All transcription methods failed for {video_id}:\n" +
        "\n".join(f"  - {err}" for err in errors)
    )
