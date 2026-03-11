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

    transcript_path = os.path.join(output_dir, entry['transcript'])
    if not os.path.isfile(transcript_path):
        return 'needs_transcript'

    summary_key = entry.get('summary')
    if not summary_key:
        return 'needs_summary'

    summary_path = os.path.join(summaries_dir, summary_key)
    if not os.path.isfile(summary_path):
        return 'needs_summary'

    return 'skip'


def update_entry(
    manifest: dict,
    video_id: str,
    title: str,
    transcript_rel: str,
    summary_rel: str | None,
) -> None:
    """Add or update a manifest entry in place."""
    entry = {
        'title': title,
        'date': date.today().isoformat(),
        'transcript': transcript_rel,
    }
    if summary_rel is not None:
        entry['summary'] = summary_rel
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
