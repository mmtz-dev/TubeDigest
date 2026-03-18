"""Listing transcripts and saving/reading summaries."""

import logging
import os
from datetime import date

log = logging.getLogger(__name__)

from src.storage import TRANSCRIPTIONS_DIR, SUMMARIES_DIR


def derive_summary_rel_path(transcript_rel: str) -> str:
    """Derive the summary .md relative path from a transcript .txt relative path."""
    return os.path.splitext(transcript_rel)[0] + '.md'


def list_transcripts() -> list[dict]:
    """Walk Transcriptions/, return list of {path, filename, subfolder, has_summary} sorted by mtime (newest first)."""
    if not os.path.isdir(TRANSCRIPTIONS_DIR):
        return []

    results = []
    for root, _dirs, files in os.walk(TRANSCRIPTIONS_DIR):
        for fname in files:
            if not fname.endswith('.txt'):
                continue
            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, TRANSCRIPTIONS_DIR)
            subfolder = os.path.dirname(rel_path) if os.sep in rel_path or '/' in rel_path else ''

            # Check if summary exists at mirror path (.md extension)
            summary_path = os.path.join(SUMMARIES_DIR, derive_summary_rel_path(rel_path))
            has_summary = os.path.isfile(summary_path)

            results.append({
                'path': rel_path,
                'filename': fname,
                'subfolder': subfolder,
                'has_summary': has_summary,
                '_mtime': os.path.getmtime(full_path),
            })

    results.sort(key=lambda x: x['_mtime'], reverse=True)
    for r in results:
        del r['_mtime']
    return results


def read_transcript(rel_path: str) -> str:
    """Read transcript file content by relative path, with recursive fallback."""
    from src.manifest import find_file_recursive

    found = find_file_recursive(TRANSCRIPTIONS_DIR, rel_path)
    if not found:
        raise FileNotFoundError(f'Transcript not found: {rel_path}')
    full_path = os.path.join(TRANSCRIPTIONS_DIR, found)
    with open(full_path, 'r', encoding='utf-8') as f:
        return f.read()


def save_summary(rel_path: str, summary_text: str, provider: str) -> str:
    """Write summary to Summaries/{rel_path}.md with metadata header. Returns the file path."""
    today = date.today().isoformat()

    header = (
        f'> **Source:** {rel_path}  \n'
        f'> **Provider:** {provider}  \n'
        f'> **Date:** {today}\n\n'
        f'---\n\n'
    )

    full_path = os.path.join(SUMMARIES_DIR, derive_summary_rel_path(rel_path))
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(header + summary_text + '\n')
    log.info("Saved summary: %s", full_path)
    return full_path
