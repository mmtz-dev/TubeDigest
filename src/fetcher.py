"""Video ID extraction, transcript + metadata fetching."""

import json
import logging
import os
import re
import tempfile
import time

from youtube_transcript_api import YouTubeTranscriptApi

from src.config import get_transcription_config
from src.usage_tracker import get_yt_api_count, increment_yt_api_count
from src.ytdlp_tracker import check_ytdlp_limit, increment_ytdlp_count

log = logging.getLogger(__name__)

YOUTUBE_URL_PATTERNS = [
    re.compile(r'(?:https?://)?(?:www\.)?youtube\.com/watch\?.*v=([a-zA-Z0-9_-]{11})'),
    re.compile(r'(?:https?://)?youtu\.be/([a-zA-Z0-9_-]{11})'),
    re.compile(r'(?:https?://)?(?:www\.)?youtube\.com/embed/([a-zA-Z0-9_-]{11})'),
    re.compile(r'(?:https?://)?(?:www\.)?youtube\.com/shorts/([a-zA-Z0-9_-]{11})'),
]

_SRT_PATTERN = re.compile(
    r'(\d+)\s+(\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2},\d{3})\s+(.*?)(?=\n\n|\Z)',
    re.DOTALL,
)


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


def _srt_ts_to_seconds(ts: str) -> float:
    h, m, rest = ts.split(':')
    s, ms = rest.split(',')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def _parse_srt_to_snippets(srt_text: str) -> list[dict]:
    snippets = []
    for match in _SRT_PATTERN.finditer(srt_text):
        start = _srt_ts_to_seconds(match.group(2))
        end = _srt_ts_to_seconds(match.group(3))
        text = match.group(4).strip().replace('\n', ' ')
        if text:
            snippets.append({
                'text': text,
                'start': start,
                'duration': round(end - start, 3),
            })
    return snippets


# ---------------------------------------------------------------------------
# Backend: pytubefix
# ---------------------------------------------------------------------------

def _fetch_metadata_pytubefix(video_id: str) -> dict:
    from pytubefix import YouTube as PytubeYT
    url = f'https://www.youtube.com/watch?v={video_id}'
    yt = PytubeYT(url)

    upload_date = None
    if yt.publish_date:
        upload_date = yt.publish_date.strftime('%Y-%m-%d')

    chapters = []
    try:
        for ch in (yt.chapters or []):
            chapters.append({
                'title': ch.title,
                'start': ch.start_seconds,
            })
    except Exception:
        pass

    return {
        'title': yt.title or 'Unknown Title',
        'channel': yt.author or 'Unknown Channel',
        'duration': yt.length,
        'upload_date': upload_date,
        'description': yt.description or '',
        'view_count': yt.views,
        'tags': yt.keywords or [],
        'categories': [],
        'chapters': chapters,
    }


def _fetch_subtitles_pytubefix(video_id: str) -> list[dict]:
    from pytubefix import YouTube as PytubeYT
    cfg = get_transcription_config()
    langs = cfg['subtitle_langs']

    url = f'https://www.youtube.com/watch?v={video_id}'
    yt = PytubeYT(url)
    captions = yt.captions

    # Try each configured language, then auto-generated variants
    codes_to_try = list(langs) + [f'a.{lang}' for lang in langs]
    for code in codes_to_try:
        try:
            cap = captions[code]
            srt_text = cap.generate_srt_captions()
            snippets = _parse_srt_to_snippets(srt_text)
            if snippets:
                log.info("pytubefix captions OK: %d snippets for %s (lang=%s)", len(snippets), video_id, code)
                return snippets
        except KeyError:
            continue

    raise RuntimeError(f"No captions found via pytubefix for {video_id} in languages {codes_to_try}")


def _download_audio_pytubefix(video_id: str, output_dir: str) -> str:
    from pytubefix import YouTube as PytubeYT
    url = f'https://www.youtube.com/watch?v={video_id}'
    yt = PytubeYT(url)

    # Prefer m4a (best for Whisper), fall back to any audio
    stream = yt.streams.filter(only_audio=True, mime_type='audio/mp4').order_by('abr').last()
    if not stream:
        stream = yt.streams.filter(only_audio=True).order_by('abr').last()
    if not stream:
        raise RuntimeError(f"No audio streams found via pytubefix for {video_id}")

    path = stream.download(output_path=output_dir, filename='audio.m4a')
    log.info("pytubefix audio downloaded: %s (%s, %s)", path, stream.mime_type, stream.abr)
    return path


# ---------------------------------------------------------------------------
# Backend: yt-dlp
# ---------------------------------------------------------------------------

def _fetch_metadata_ytdlp(video_id: str) -> dict:
    if check_ytdlp_limit():
        raise RuntimeError("yt-dlp daily limit reached")
    import yt_dlp
    url = f'https://www.youtube.com/watch?v={video_id}'
    opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': False,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    increment_ytdlp_count()

    upload_date = None
    raw_date = info.get('upload_date')  # YYYYMMDD string
    if raw_date and len(raw_date) == 8:
        upload_date = f'{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}'

    chapters = []
    for ch in (info.get('chapters') or []):
        chapters.append({
            'title': ch.get('title', ''),
            'start': ch.get('start_time', 0),
        })

    return {
        'title': info.get('title', 'Unknown Title'),
        'channel': info.get('channel', info.get('uploader', 'Unknown Channel')),
        'duration': info.get('duration'),
        'upload_date': upload_date,
        'description': info.get('description', ''),
        'view_count': info.get('view_count'),
        'tags': info.get('tags') or [],
        'categories': info.get('categories') or [],
        'chapters': chapters,
    }


def _fetch_subtitles_ytdlp(video_id: str) -> list[dict]:
    if check_ytdlp_limit():
        raise RuntimeError("yt-dlp daily limit reached")
    import yt_dlp
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
        increment_ytdlp_count()

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


def _download_audio_ytdlp(video_id: str, output_dir: str) -> str:
    if check_ytdlp_limit():
        raise RuntimeError("yt-dlp daily limit reached")
    import yt_dlp
    url = f'https://www.youtube.com/watch?v={video_id}'
    audio_path = os.path.join(output_dir, 'audio.m4a')
    opts = {
        'quiet': True,
        'no_warnings': True,
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'outtmpl': audio_path,
    }

    log.info("Downloading audio via yt-dlp for %s", video_id)
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    increment_ytdlp_count()

    if not os.path.exists(audio_path):
        # yt-dlp may have used a different extension
        for fname in os.listdir(output_dir):
            audio_path = os.path.join(output_dir, fname)
            break

    log.info("yt-dlp audio downloaded: %s", audio_path)
    return audio_path


# ---------------------------------------------------------------------------
# Backend dispatch helpers
# ---------------------------------------------------------------------------

_METADATA_BACKENDS = {
    'pytubefix': _fetch_metadata_pytubefix,
    'ytdlp': _fetch_metadata_ytdlp,
}

_SUBTITLE_BACKENDS = {
    'pytubefix': _fetch_subtitles_pytubefix,
    'ytdlp': _fetch_subtitles_ytdlp,
}

_AUDIO_BACKENDS = {
    'pytubefix': _download_audio_pytubefix,
    'ytdlp': _download_audio_ytdlp,
}


def _get_backends() -> list[str]:
    return get_transcription_config().get('video_backend', ['pytubefix', 'ytdlp'])


def _try_backends(backend_map: dict, *args, label: str = '') -> tuple[any, str]:
    """Try backends in config order. Returns (result, backend_name)."""
    backends = _get_backends()
    errors = []
    for name in backends:
        fn = backend_map.get(name)
        if not fn:
            continue
        try:
            log.info("[%s] trying %s backend...", label, name)
            result = fn(*args)
            log.info("[%s] succeeded with %s backend", label, name)
            return result, name
        except Exception as e:
            log.warning("[%s] %s backend failed: %s", label, name, e)
            errors.append(f"{name}: {e}")
    raise RuntimeError(
        f"All backends failed for {label}:\n" +
        "\n".join(f"  - {err}" for err in errors)
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_video_metadata(video_id: str) -> dict:
    """Fetch video title, channel, and duration. Tries backends in config order."""
    log.info("Fetching metadata for video: %s", video_id)
    meta, backend = _try_backends(_METADATA_BACKENDS, video_id, label=f"metadata:{video_id}")
    log.info(
        "Metadata OK [%s]: \"%s\" by %s (duration=%s, uploaded=%s, views=%s)",
        backend, meta['title'], meta['channel'],
        meta.get('duration'), meta.get('upload_date'), meta.get('view_count'),
    )
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


def fetch_transcript_subtitles(video_id: str) -> list[dict]:
    """Fetch subtitles using the configured video backend. Returns list of {text, start, duration} dicts."""
    result, backend = _try_backends(_SUBTITLE_BACKENDS, video_id, label=f"subtitles:{video_id}")
    log.info("Subtitles OK [%s]: %d snippets for %s", backend, len(result), video_id)
    return result


def fetch_transcript_whisper(video_id: str, emit_fn=None) -> list[dict]:
    """Download audio using configured backend, transcribe with local Whisper."""
    cfg = get_transcription_config()
    if not cfg['whisper_enabled']:
        raise RuntimeError("Whisper is disabled in config.yaml")

    model_name = cfg['whisper_model']
    device_setting = cfg['whisper_device']

    import whisper
    import torch

    if device_setting == 'auto':
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
    else:
        device = device_setting

    if emit_fn:
        emit_fn('status', message=f'Loading Whisper model "{model_name}" on {device}...')
    log.info("Loading Whisper model '%s' on device '%s'", model_name, device)
    model = whisper.load_model(model_name, device=device)

    with tempfile.TemporaryDirectory() as tmpdir:
        if emit_fn:
            emit_fn('status', message='Downloading audio for Whisper transcription...')

        audio_path, audio_backend = _try_backends(_AUDIO_BACKENDS, video_id, tmpdir, label=f"audio:{video_id}")
        log.info("Audio downloaded [%s]: %s", audio_backend, audio_path)

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
    'pytubefix_subtitles': lambda vid, ts, emit: fetch_transcript_subtitles(vid),
    'ytdlp_subtitles': lambda vid, ts, emit: _fetch_subtitles_ytdlp(vid),
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
        methods = ['youtube_transcript_api', 'pytubefix_subtitles']
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
    subtitles_failed = False

    for method_name in methods:
        fn = _METHOD_MAP.get(method_name)
        if not fn:
            log.warning("Unknown transcription method: %s", method_name)
            continue

        if method_name == 'whisper' and not cfg['whisper_enabled']:
            log.info("Skipping whisper (disabled in config)")
            continue

        # Emit warning before Whisper fallback if other methods failed
        if method_name == 'whisper' and yt_api_failed and subtitles_failed and emit_fn:
            emit_fn(
                'warning',
                message='Transcript and subtitle methods failed. '
                        'Falling back to Whisper (local transcription, this may be slow)...',
            )

        try:
            log.info("[transcription:%s] trying method: %s", video_id, method_name)
            if emit_fn:
                emit_fn('status', message=f'Trying {method_name} for transcript...')
            transcript = fn(video_id, include_timestamps, emit_fn)
            log.info(
                "[transcription:%s] succeeded with %s (%d snippets)",
                video_id, method_name, len(transcript),
            )
            return transcript, method_name
        except Exception as e:
            log.warning("[transcription:%s] %s failed: %s", video_id, method_name, e)
            errors.append(f"{method_name}: {e}")
            if method_name == 'youtube_transcript_api':
                yt_api_failed = True
            elif method_name in ('pytubefix_subtitles', 'ytdlp_subtitles'):
                subtitles_failed = True

    raise RuntimeError(
        f"All transcription methods failed for {video_id}:\n" +
        "\n".join(f"  - {err}" for err in errors)
    )
