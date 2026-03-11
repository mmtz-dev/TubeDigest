"""Background job manager with threading and queue-based progress reporting."""

import json
import logging
import os
import random
import threading
import time
import uuid
from queue import Queue

log = logging.getLogger(__name__)

from src.fetcher import extract_video_id, fetch_video_metadata, fetch_transcript_auto
from src.manifest import load_manifest, save_manifest, check_status, update_entry
from src.playlist import is_playlist_url, extract_playlist_videos
from src.storage import format_transcript_content, save_transcript, BASE_DIR
from src.summary_storage import SUMMARIES_DIR


class JobManager:
    """Manages background transcript-fetching jobs."""

    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._manifest_lock = threading.Lock()

    def create_job(self, urls: list[str], include_timestamps: bool = True) -> str:
        """Create a new job and start processing in a background thread."""
        job_id = uuid.uuid4().hex[:12]
        queue = Queue()
        self._jobs[job_id] = {
            'queue': queue,
            'status': 'running',
            'succeeded': 0,
            'failed': 0,
            'total': 0,
        }
        thread = threading.Thread(
            target=self._process_job,
            args=(job_id, urls, include_timestamps),
            daemon=True,
        )
        thread.start()
        return job_id

    def get_queue(self, job_id: str) -> Queue | None:
        job = self._jobs.get(job_id)
        return job['queue'] if job else None

    def get_status(self, job_id: str) -> dict | None:
        job = self._jobs.get(job_id)
        if not job:
            return None
        return {
            'status': job['status'],
            'succeeded': job['succeeded'],
            'failed': job['failed'],
            'total': job['total'],
        }

    def _emit(self, job_id: str, event_type: str, **data):
        queue = self._jobs[job_id]['queue']
        queue.put({'type': event_type, **data})

    def _process_job(self, job_id: str, urls: list[str], include_timestamps: bool):
        job = self._jobs[job_id]
        try:
            videos = self._resolve_videos(job_id, urls)
            total = len(videos)
            job['total'] = total
            self._emit(job_id, 'total', count=total)

            if total == 0:
                self._emit(job_id, 'error', current=0, video_id='', message='No valid videos found.')
                self._finish_job(job_id)
                return

            is_batch = total > 1

            with self._manifest_lock:
                manifest = load_manifest(BASE_DIR)

            for i, video in enumerate(videos, 1):
                video_id = video['video_id']
                playlist_name = video.get('playlist_name')

                # Duplicate check
                status = check_status(manifest, video_id, BASE_DIR, SUMMARIES_DIR)
                if status == 'skip':
                    entry = manifest[video_id]
                    log.info("Skipping %s — already has transcript and summary: \"%s\"", video_id, entry['title'])
                    job['succeeded'] += 1
                    self._emit(
                        job_id, 'success',
                        current=i, title=entry['title'],
                        skipped=True,
                        message=f'Already processed: "{entry["title"]}"',
                    )
                    continue

                self._emit(
                    job_id, 'progress',
                    current=i, total=total,
                    message=f'Processing video {i}/{total}: {video_id}',
                )
                try:
                    metadata = fetch_video_metadata(video_id)
                    title = metadata['title']

                    duration = metadata.get('duration')

                    def video_emit(event_type, **data):
                        self._emit(job_id, event_type, **data)

                    self._emit(
                        job_id, 'status',
                        message=f'Fetching transcript for: {title}',
                    )
                    transcript, method_used = fetch_transcript_auto(
                        video_id, duration, include_timestamps, emit_fn=video_emit,
                    )
                    content = format_transcript_content(title, video_id, transcript, include_timestamps)
                    filepath = save_transcript(title, video_id, content, playlist_name)

                    transcript_rel = os.path.relpath(filepath, BASE_DIR)
                    with self._manifest_lock:
                        update_entry(manifest, video_id, title, transcript_rel, None)
                        save_manifest(BASE_DIR, manifest)

                    job['succeeded'] += 1
                    self._emit(job_id, 'success', current=i, title=title)

                except Exception as e:
                    job['failed'] += 1
                    self._emit(
                        job_id, 'error',
                        current=i, video_id=video_id,
                        message=str(e),
                    )

                # Rate limiting for batches
                if is_batch and i < total:
                    if i % 10 == 0:
                        delay = 15
                        self._emit(job_id, 'status', message=f'Pausing {delay}s to avoid rate limits...')
                        time.sleep(delay)
                    else:
                        delay = random.uniform(2, 5)
                        self._emit(job_id, 'status', message=f'Waiting {delay:.1f}s before next request...')
                        time.sleep(delay)

        except Exception as e:
            self._emit(job_id, 'error', current=0, video_id='', message=f'Job failed: {e}')

        self._finish_job(job_id)

    def _finish_job(self, job_id: str):
        job = self._jobs[job_id]
        job['status'] = 'completed'
        self._emit(
            job_id, 'summary',
            succeeded=job['succeeded'],
            failed=job['failed'],
            total=job['total'],
        )
        self._emit(job_id, 'done')

    def create_summarization_job(self, transcript_paths: list[str]) -> str:
        """Create a new summarization job and start processing in a background thread."""
        job_id = uuid.uuid4().hex[:12]
        queue = Queue()
        self._jobs[job_id] = {
            'queue': queue,
            'status': 'running',
            'succeeded': 0,
            'failed': 0,
            'total': 0,
        }
        thread = threading.Thread(
            target=self._process_summarization_job,
            args=(job_id, transcript_paths),
            daemon=True,
        )
        thread.start()
        return job_id

    def _process_summarization_job(self, job_id: str, paths: list[str]):
        from src.config import get_summarization_config
        from src.summarizer import summarize
        from src.summary_storage import read_transcript, save_summary

        job = self._jobs[job_id]
        try:
            total = len(paths)
            job['total'] = total
            self._emit(job_id, 'total', count=total)

            if total == 0:
                self._emit(job_id, 'error', current=0, video_id='', message='No transcripts selected.')
                self._finish_job(job_id)
                return

            cfg = get_summarization_config()

            with self._manifest_lock:
                manifest = load_manifest(BASE_DIR)

            for i, rel_path in enumerate(paths, 1):
                # Check if summary already exists
                summary_rel = os.path.splitext(rel_path)[0] + '.md'
                summary_path = os.path.join(SUMMARIES_DIR, summary_rel)
                if os.path.isfile(summary_path):
                    log.info("Skipping summarization — summary already exists: %s", summary_rel)
                    job['succeeded'] += 1
                    self._emit(
                        job_id, 'success',
                        current=i, title=rel_path,
                        skipped=True,
                        message=f'Already summarized: {rel_path}',
                    )
                    continue

                self._emit(
                    job_id, 'progress',
                    current=i, total=total,
                    message=f'Summarizing {i}/{total}: {rel_path}',
                )
                try:
                    transcript_text = read_transcript(rel_path)

                    def job_emit(event_type, **data):
                        self._emit(job_id, event_type, **data)

                    summary_text, provider_name = summarize(transcript_text, cfg, emit_fn=job_emit)
                    save_summary(rel_path, summary_text, provider_name)

                    summary_rel = os.path.splitext(rel_path)[0] + '.md'
                    # Update manifest — find video_id from existing entry or parse from transcript
                    video_id = self._find_video_id_for_transcript(manifest, rel_path, transcript_text)
                    if video_id:
                        with self._manifest_lock:
                            entry = manifest.get(video_id, {})
                            title = entry.get('title', os.path.basename(rel_path))
                            update_entry(manifest, video_id, title, rel_path, summary_rel)
                            save_manifest(BASE_DIR, manifest)

                    job['succeeded'] += 1
                    self._emit(job_id, 'success', current=i, title=rel_path)
                except Exception as e:
                    job['failed'] += 1
                    self._emit(
                        job_id, 'error',
                        current=i, video_id='',
                        message=f'{rel_path}: {e}',
                    )
        except Exception as e:
            self._emit(job_id, 'error', current=0, video_id='', message=f'Job failed: {e}')

    @staticmethod
    def _find_video_id_for_transcript(manifest: dict, rel_path: str, transcript_text: str) -> str | None:
        """Find the video ID for a transcript, checking manifest first then parsing the file."""
        # Check manifest for matching transcript path
        for vid, entry in manifest.items():
            if entry.get('transcript') == rel_path:
                return vid

        # Parse "Video ID: xxx" from transcript content
        for line in transcript_text.splitlines()[:5]:
            if line.startswith('Video ID:'):
                return line.split(':', 1)[1].strip()

        return None

        self._finish_job(job_id)

    def _resolve_videos(self, job_id: str, urls: list[str]) -> list[dict]:
        """Expand URLs into a flat list of {video_id, playlist_name?} dicts."""
        videos = []
        for url in urls:
            url = url.strip()
            if not url:
                continue

            if is_playlist_url(url):
                self._emit(job_id, 'status', message=f'Extracting playlist: {url}')
                try:
                    playlist_info = extract_playlist_videos(url)
                    playlist_name = playlist_info['title']
                    for v in playlist_info['videos']:
                        videos.append({
                            'video_id': v['video_id'],
                            'playlist_name': playlist_name,
                        })
                    self._emit(
                        job_id, 'status',
                        message=f'Found {len(playlist_info["videos"])} videos in playlist "{playlist_name}"',
                    )
                except Exception as e:
                    self._emit(
                        job_id, 'error',
                        current=0, video_id='',
                        message=f'Failed to extract playlist {url}: {e}',
                    )
            else:
                video_id = extract_video_id(url)
                if video_id:
                    videos.append({'video_id': video_id})
                else:
                    self._emit(
                        job_id, 'error',
                        current=0, video_id='',
                        message=f'Could not extract video ID from: {url}',
                    )

        return videos
