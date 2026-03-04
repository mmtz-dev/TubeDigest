"""File naming, formatting, and saving transcripts."""

import os
import re
from datetime import date


_DEFAULT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'Transcriptions')
BASE_DIR = os.environ.get('TRANSCRIPTIONS_DIR', _DEFAULT_DIR)


def sanitize_filename(name: str) -> str:
    """Remove or replace characters that are unsafe for filenames."""
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', '_', name.strip())
    name = name[:200]  # Limit length
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
) -> str:
    """Format transcript into the output .txt content."""
    today = date.today().isoformat()
    url = f'https://www.youtube.com/watch?v={video_id}'
    separator = '\u2500' * 44  # ────────────

    lines = [
        f'Title:    {title}',
        f'Video ID: {video_id}',
        f'URL:      {url}',
        f'Date:     {today}',
        separator,
    ]

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

    return filepath
