"""JSON manifest for tracking processed videos and detecting duplicates."""

import json
import os
from datetime import date

MANIFEST_FILENAME = '.processed.json'


def load_manifest(output_dir: str) -> dict:
    """Read .processed.json from output_dir. Returns empty dict if missing."""
    path = os.path.join(output_dir, MANIFEST_FILENAME)
    if not os.path.isfile(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_manifest(output_dir: str, manifest: dict) -> None:
    """Write .processed.json atomically using a temp file + rename."""
    os.makedirs(output_dir, exist_ok=True)
    final_path = os.path.join(output_dir, MANIFEST_FILENAME)
    tmp_path = final_path + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, final_path)


def find_file_recursive(base_dir: str, rel_path: str) -> str | None:
    """Find a file by relative path, falling back to a recursive basename search.

    Returns the (possibly updated) relative path if found, or None.
    """
    if os.path.isfile(os.path.join(base_dir, rel_path)):
        return rel_path

    target = os.path.basename(rel_path)
    for root, _dirs, files in os.walk(base_dir):
        if target in files:
            return os.path.relpath(os.path.join(root, target), base_dir)

    return None


def check_status(
    manifest: dict,
    video_id: str,
    output_dir: str,
    summaries_dir: str,
) -> str:
    """Return processing status for a video.

    Returns:
        "skip"              — transcript and summary both exist on disk
        "needs_summary"     — transcript exists but summary is missing
        "needs_transcript"  — transcript missing (implies summary also needed)
    """
    entry = manifest.get(video_id)
    if not entry:
        return 'needs_transcript'

    found_transcript = find_file_recursive(output_dir, entry['transcript'])
    if not found_transcript:
        return 'needs_transcript'
    entry['transcript'] = found_transcript

    summary_key = entry.get('summary')
    if not summary_key:
        return 'needs_summary'

    found_summary = find_file_recursive(summaries_dir, summary_key)
    if not found_summary:
        return 'needs_summary'
    entry['summary'] = found_summary

    return 'skip'


def update_entry(
    manifest: dict,
    video_id: str,
    title: str,
    transcript_rel: str,
    summary_rel: str | None,
    metadata: dict | None = None,
) -> None:
    """Add or update a manifest entry in place."""
    entry = {
        'title': title,
        'date': date.today().isoformat(),
        'transcript': transcript_rel,
    }
    if summary_rel is not None:
        entry['summary'] = summary_rel

    if metadata:
        if metadata.get('channel'):
            entry['channel'] = metadata['channel']
        if metadata.get('upload_date'):
            entry['upload_date'] = metadata['upload_date']
        if metadata.get('duration') is not None:
            entry['duration'] = metadata['duration']
        if metadata.get('view_count') is not None:
            entry['view_count'] = metadata['view_count']
        if metadata.get('tags'):
            entry['tags'] = metadata['tags']
        if metadata.get('categories'):
            entry['categories'] = metadata['categories']

    manifest[video_id] = entry


def find_video_id_for_transcript(manifest: dict, rel_path: str, transcript_text: str) -> str | None:
    """Find the video ID for a transcript, checking manifest first then parsing the file."""
    for vid, entry in manifest.items():
        if entry.get('transcript') == rel_path:
            return vid

    for line in transcript_text.splitlines()[:5]:
        if line.startswith('Video ID:'):
            return line.split(':', 1)[1].strip()

    return None
