"""File naming, formatting, and saving transcripts."""

import logging
import os
import re
from datetime import date

log = logging.getLogger(__name__)


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRANSCRIPTIONS_DIR = os.environ.get('TRANSCRIPTIONS_DIR', os.path.join(_PROJECT_ROOT, 'Transcriptions'))
SUMMARIES_DIR = os.environ.get('SUMMARIES_DIR', os.path.join(_PROJECT_ROOT, 'Summaries'))
BASE_DIR = TRANSCRIPTIONS_DIR  # backward compat alias


def sanitize_filename(name: str) -> str:
    """Normalize to alphanumeric and underscores only."""
    name = re.sub(r'[^a-zA-Z0-9\s]', '', name)
    name = re.sub(r'\s+', '_', name.strip())
    name = re.sub(r'_+', '_', name)
    name = name.strip('_')
    name = name[:200]
    return name


def format_timestamp(seconds: float) -> str:
    """Convert seconds to [HH:MM:SS] or [MM:SS] format."""
    total = int(seconds)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f'[{h:02d}:{m:02d}:{s:02d}]'
    return f'[{m:02d}:{s:02d}]'


def format_transcript_content(
    title: str,
    video_id: str,
    transcript: list[dict],
    include_timestamps: bool = True,
    metadata: dict | None = None,
) -> str:
    """Format transcript into the output .txt content."""
    today = date.today().isoformat()
    url = f'https://www.youtube.com/watch?v={video_id}'
    separator = '\u2500' * 44  # ────────────
    meta = metadata or {}

    lines = [
        f'Title:       {title}',
        f'Channel:     {meta.get("channel", "Unknown")}',
        f'Video ID:    {video_id}',
        f'URL:         {url}',
    ]

    if meta.get('upload_date'):
        lines.append(f'Upload Date: {meta["upload_date"]}')

    lines.append(f'Saved:       {today}')

    if meta.get('duration') is not None:
        lines.append(f'Duration:    {format_timestamp(meta["duration"])}')

    if meta.get('view_count') is not None:
        lines.append(f'Views:       {meta["view_count"]:,}')

    if meta.get('tags'):
        lines.append(f'Tags:        {", ".join(meta["tags"])}')

    if meta.get('categories'):
        lines.append(f'Categories:  {", ".join(meta["categories"])}')

    if meta.get('chapters'):
        lines.append('')
        lines.append('Chapters:')
        for ch in meta['chapters']:
            ts = format_timestamp(ch['start'])
            lines.append(f'  {ts} {ch["title"]}')

    if meta.get('description'):
        lines.append('')
        lines.append('Description:')
        lines.append(meta['description'])

    lines.append(separator)

    for entry in transcript:
        text = entry['text']
        if include_timestamps:
            ts = format_timestamp(entry['start'])
            lines.append(f'{ts} {text}')
        else:
            lines.append(text)

    return '\n'.join(lines) + '\n'


def save_transcript(
    title: str,
    video_id: str,
    content: str,
    playlist_name: str | None = None,
) -> str:
    """Save transcript content to a .txt file. Returns the file path."""
    today = date.today().isoformat()
    safe_title = sanitize_filename(title)
    filename = f'{safe_title}_{today}.txt'

    if playlist_name:
        safe_playlist = sanitize_filename(playlist_name)
        folder = os.path.join(BASE_DIR, f'{safe_playlist}_{today}')
    else:
        folder = BASE_DIR

    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    log.info("Saved transcript: %s", filepath)
    return filepath
