"""Shared video processing pipeline used by both CLI and web UI."""

import os
import random
import time
from dataclasses import dataclass

from src.categorizer import categorize, move_to_category, scan_existing_categories
from src.fetcher import extract_video_id, fetch_video_metadata, fetch_transcript_auto
from src.manifest import check_status, find_file_recursive, find_video_id_for_transcript, update_entry
from src.playlist import is_playlist_url, extract_playlist_videos
from src.storage import format_transcript_content, save_transcript
from src.summary_storage import derive_summary_rel_path, read_transcript, save_summary


@dataclass
class VideoTarget:
    video_id: str
    playlist_name: str | None = None


@dataclass
class VideoResult:
    outcome: str  # 'ok', 'skip', 'error'
    title: str = ''
    transcript_rel: str = ''
    error: str = ''


@dataclass
class SummaryResult:
    outcome: str  # 'ok', 'skip', 'error'
    summary_rel: str = ''
    provider: str = ''
    error: str = ''


@dataclass
class CategorizationResult:
    outcome: str  # 'ok', 'skip', 'error'
    category: str = ''
    new_transcript_rel: str = ''
    new_summary_rel: str = ''
    error: str = ''


def _noop_emit(event_type: str, **data):
    pass


def expand_urls(urls: list[str], emit_fn=None) -> list[VideoTarget]:
    """Expand raw URLs into a flat list of VideoTargets (playlists expanded)."""
    emit = emit_fn or _noop_emit
    targets: list[VideoTarget] = []

    for url in urls:
        url = url.strip()
        if not url:
            continue

        if is_playlist_url(url):
            emit('status', message=f'Extracting playlist: {url}')
            try:
                playlist_info = extract_playlist_videos(url)
                playlist_name = playlist_info['title']
                for v in playlist_info['videos']:
                    targets.append(VideoTarget(v['video_id'], playlist_name))
                emit('status', message=f'Found {len(playlist_info["videos"])} videos in playlist "{playlist_name}"')
            except Exception as e:
                emit('error', current=0, video_id='', message=f'Failed to extract playlist {url}: {e}')
        else:
            video_id = extract_video_id(url)
            if video_id:
                targets.append(VideoTarget(video_id))
            else:
                emit('error', current=0, video_id='', message=f'Could not extract video ID from: {url}')

    return targets


def process_video(
    video_id: str,
    playlist_name: str | None,
    manifest: dict,
    transcriptions_dir: str,
    summaries_dir: str,
    include_timestamps: bool = True,
    force: bool = False,
    emit_fn=None,
) -> VideoResult:
    """Fetch and save a single video transcript. Returns a VideoResult."""
    emit = emit_fn or _noop_emit

    status = 'needs_transcript' if force else check_status(
        manifest, video_id, transcriptions_dir, summaries_dir,
    )

    if status == 'skip':
        entry = manifest[video_id]
        return VideoResult('skip', title=entry['title'])

    if status == 'needs_summary':
        entry = manifest[video_id]
        return VideoResult('ok', title=entry['title'], transcript_rel=entry['transcript'])

    # needs_transcript
    try:
        from src.config import get_transcription_config
        backends = get_transcription_config().get('video_backend', ['pytubefix', 'ytdlp'])
        emit('status', message=f'Video backend: {backends[0]} (fallback: {", ".join(backends[1:])})')

        metadata = fetch_video_metadata(video_id)
        title = metadata['title']
        duration = metadata.get('duration')

        emit('status', message=f'Fetching transcript for: {title}')
        transcript, method = fetch_transcript_auto(
            video_id, duration, include_timestamps, emit_fn=emit,
        )
        emit('status', message=f'Transcript fetched via: {method}')
        content = format_transcript_content(title, video_id, transcript, include_timestamps, metadata=metadata)
        filepath = save_transcript(title, video_id, content, playlist_name)
        transcript_rel = os.path.relpath(filepath, transcriptions_dir)

        update_entry(manifest, video_id, title, transcript_rel, None, metadata=metadata)
        return VideoResult('ok', title=title, transcript_rel=transcript_rel)

    except Exception as e:
        return VideoResult('error', title=video_id, error=str(e))


def process_summary(
    transcript_rel: str,
    manifest: dict,
    transcriptions_dir: str,
    summaries_dir: str,
    emit_fn=None,
) -> SummaryResult:
    """Summarize a single transcript. Returns a SummaryResult."""
    from src.config import get_summarization_config
    from src.summarizer import summarize

    emit = emit_fn or _noop_emit

    summary_rel = derive_summary_rel_path(transcript_rel)
    if find_file_recursive(summaries_dir, summary_rel):
        return SummaryResult('skip', summary_rel=summary_rel)

    try:
        transcript_text = read_transcript(transcript_rel)
        cfg = get_summarization_config()
        summary_text, provider_name = summarize(transcript_text, cfg, emit_fn=emit)
        save_summary(transcript_rel, summary_text, provider_name)

        # Update manifest if we can find the video_id
        video_id = find_video_id_for_transcript(manifest, transcript_rel, transcript_text)
        if video_id:
            entry = manifest.get(video_id, {})
            title = entry.get('title', os.path.basename(transcript_rel))
            update_entry(manifest, video_id, title, transcript_rel, summary_rel)

        return SummaryResult('ok', summary_rel=summary_rel, provider=provider_name)

    except Exception as e:
        return SummaryResult('error', error=str(e))


def process_categorization(
    transcript_rel: str,
    summary_rel: str,
    manifest: dict,
    transcriptions_dir: str,
    summaries_dir: str,
    emit_fn=None,
) -> CategorizationResult:
    """Categorize a summarized video and move files into category subfolders."""
    emit = emit_fn or _noop_emit

    try:
        # Read the summary file
        summary_path = os.path.join(summaries_dir, summary_rel)
        if not os.path.isfile(summary_path):
            return CategorizationResult('error', error=f'Summary not found: {summary_rel}')

        with open(summary_path, 'r', encoding='utf-8') as f:
            summary_text = f.read()

        # Get video title from manifest
        video_id = find_video_id_for_transcript(manifest, transcript_rel, '')
        if video_id:
            video_title = manifest.get(video_id, {}).get('title', os.path.basename(transcript_rel))
        else:
            video_title = os.path.basename(transcript_rel)

        # Scan existing category folders
        existing = scan_existing_categories(transcriptions_dir)

        # Ask AI for category
        from src.config import get_categorization_config
        cfg = get_categorization_config()
        category = categorize(summary_text, video_title, existing, cfg, emit_fn=emit)

        # Move files into category subfolder
        new_transcript_rel, new_summary_rel = move_to_category(
            transcript_rel, summary_rel, category,
            transcriptions_dir, summaries_dir,
        )

        # Update manifest entry in-place
        if video_id and video_id in manifest:
            manifest[video_id]['transcript'] = new_transcript_rel
            manifest[video_id]['summary'] = new_summary_rel
            manifest[video_id]['category'] = category

        emit('status', message=f'Categorized as: {category}')
        return CategorizationResult(
            'ok', category=category,
            new_transcript_rel=new_transcript_rel,
            new_summary_rel=new_summary_rel,
        )

    except Exception as e:
        return CategorizationResult('error', error=str(e))


def apply_rate_limit(index: int, total: int, emit_fn=None):
    """Sleep between videos in a batch to avoid rate limits. No-op for last item."""
    if index >= total:
        return

    emit = emit_fn or _noop_emit

    if index % 10 == 0:
        delay = 15
        emit('status', message=f'Pausing {delay}s to avoid rate limits...')
        time.sleep(delay)
    else:
        delay = random.uniform(2, 5)
        emit('status', message=f'Waiting {delay:.1f}s before next request...')
        time.sleep(delay)
