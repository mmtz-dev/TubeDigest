"""Listing transcripts and saving/reading summaries."""

import logging
import os
import re
from datetime import date

log = logging.getLogger(__name__)

from src.storage import TRANSCRIPTIONS_DIR, SUMMARIES_DIR


_UNCATEGORIZED_DISPLAY = 'Uncategorized'


def canonical_category_key(name: str) -> str:
    """Reduce a category name to a slug: lowercase, alphanumerics only.

    `AI_Agents`, `AI & Agents`, and `ai-agents` all collapse to `aiagents`,
    which lets the UI merge duplicate folders under one tile. Empty input
    returns `''` (the Uncategorized bucket).
    """
    return re.sub(r'[^a-z0-9]+', '', (name or '').lower())


def display_category_name(folder_name: str) -> str:
    """Render a folder name for display: `_` → space, collapse whitespace."""
    if not folder_name:
        return _UNCATEGORIZED_DISPLAY
    s = folder_name.replace('_', ' ')
    s = re.sub(r'\s+', ' ', s).strip()
    return s or _UNCATEGORIZED_DISPLAY


def derive_summary_rel_path(transcript_rel: str) -> str:
    """Derive the summary .md relative path from a transcript .txt relative path."""
    return os.path.splitext(transcript_rel)[0] + '.md'


def validate_rel_path(p: str) -> bool:
    """Return True if the relative path is safe (no traversal, not absolute, no null bytes)."""
    if not p or '\x00' in p:
        return False
    if os.path.isabs(p) or p.startswith('..'):
        return False
    if os.sep + '..' in p or '/..' in p:
        return False
    return True


def list_transcripts() -> list[dict]:
    """Walk Transcriptions/, return list of {path, filename, subfolder, category_key, has_summary} sorted by mtime (newest first)."""
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
            # Only the top-level folder counts as the category.
            top_folder = subfolder.split(os.sep)[0] if subfolder else ''

            # Check if summary exists at mirror path (.md extension)
            summary_path = os.path.join(SUMMARIES_DIR, derive_summary_rel_path(rel_path))
            has_summary = os.path.isfile(summary_path)

            results.append({
                'path': rel_path,
                'filename': fname,
                'subfolder': subfolder,
                'category_key': canonical_category_key(top_folder),
                'has_summary': has_summary,
                'mtime': os.path.getmtime(full_path),
            })

    results.sort(key=lambda x: x['mtime'], reverse=True)
    return results


def list_categories_with_counts() -> list[dict]:
    """Return one entry per canonical category key, merging duplicate folders.

    Entry shape:
        {
          'key': 'aiagents',            # canonical slug (stable URL id)
          'display': 'AI Agents',       # human-friendly label
          'folders': ['AI_Agents', 'AI & Agents'],
          'count': 68,
          'summarized_count': 45,
        }
    Sorted by count (desc) then display name.
    """
    if not os.path.isdir(TRANSCRIPTIONS_DIR):
        return []

    items = list_transcripts()

    per_key: dict[str, dict] = {}
    folder_counts: dict[str, int] = {}

    for item in items:
        top = item['subfolder'].split(os.sep)[0] if item['subfolder'] else ''
        key = item['category_key']
        bucket = per_key.setdefault(key, {
            'key': key,
            'folders': set(),
            'count': 0,
            'summarized_count': 0,
        })
        if top:
            bucket['folders'].add(top)
        bucket['count'] += 1
        if item['has_summary']:
            bucket['summarized_count'] += 1
        if top:
            folder_counts[top] = folder_counts.get(top, 0) + 1

    results = []
    for key, bucket in per_key.items():
        folders = sorted(bucket['folders'])
        display = _pick_display_name(folders, folder_counts)
        results.append({
            'key': key,
            'display': display,
            'folders': folders,
            'count': bucket['count'],
            'summarized_count': bucket['summarized_count'],
        })

    results.sort(key=lambda c: (-c['count'], c['display'].lower()))
    return results


def _pick_display_name(folders: list[str], folder_counts: dict[str, int]) -> str:
    """Pick the display label for a group of fuzzy-duplicate folders.

    Preference order:
      1. Highest item count (legacy folders with most content win).
      2. Most non-alphanumeric characters (spaces/ampersands read better
         than underscores: `AI & Agents` > `AI_Agents`).
      3. Alphabetical.
    """
    if not folders:
        return _UNCATEGORIZED_DISPLAY

    def score(folder: str):
        count = folder_counts.get(folder, 0)
        punct = sum(1 for ch in folder if not ch.isalnum())
        return (-count, -punct, folder.lower())

    best = min(folders, key=score)
    return display_category_name(best)


def read_summary(rel_path: str) -> str | None:
    """Read a summary file by transcript rel_path, stripping the metadata header.

    Returns None if the summary file doesn't exist. The header ends at the first
    `\\n---\\n\\n` delimiter (see save_summary); if no delimiter is found, the
    full file contents are returned as a defensive fallback.
    """
    full_path = os.path.join(SUMMARIES_DIR, derive_summary_rel_path(rel_path))
    if not os.path.isfile(full_path):
        return None
    with open(full_path, 'r', encoding='utf-8') as f:
        content = f.read()
    delimiter = '\n---\n\n'
    idx = content.find(delimiter)
    if idx == -1:
        return content
    return content[idx + len(delimiter):]


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
