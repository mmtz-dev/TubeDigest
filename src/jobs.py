"""Background job manager with threading and queue-based progress reporting."""

import logging
import os
import threading
import uuid
from queue import Queue

log = logging.getLogger(__name__)

from src.manifest import load_manifest, save_manifest, find_file_recursive
from src.pipeline import expand_urls, process_video, process_summary, process_categorization, apply_rate_limit
from src.storage import BASE_DIR
from src.summary_storage import SUMMARIES_DIR, derive_summary_rel_path


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
            def emit(event_type, **data):
                self._emit(job_id, event_type, **data)

            videos = expand_urls(urls, emit_fn=emit)
            total = len(videos)
            job['total'] = total
            self._emit(job_id, 'total', count=total)

            if total == 0:
                self._emit(job_id, 'error', current=0, video_id='', message='No valid videos found.')
                self._finish_job(job_id)
                return

            with self._manifest_lock:
                manifest = load_manifest(BASE_DIR)

            for i, target in enumerate(videos, 1):
                self._emit(
                    job_id, 'progress',
                    current=i, total=total,
                    message=f'Processing video {i}/{total}: {target.video_id}',
                )

                with self._manifest_lock:
                    result = process_video(
                        target.video_id, target.playlist_name,
                        manifest, BASE_DIR, SUMMARIES_DIR,
                        include_timestamps=include_timestamps,
                        emit_fn=emit,
                    )
                    if result.outcome != 'error':
                        save_manifest(BASE_DIR, manifest)

                if result.outcome == 'skip':
                    log.info("Skipping %s — already has transcript and summary: \"%s\"", target.video_id, result.title)
                    job['succeeded'] += 1
                    self._emit(
                        job_id, 'success',
                        current=i, title=result.title,
                        skipped=True,
                        message=f'Already processed: "{result.title}"',
                    )
                elif result.outcome == 'ok':
                    job['succeeded'] += 1
                    self._emit(job_id, 'success', current=i, title=result.title)
                else:
                    job['failed'] += 1
                    self._emit(
                        job_id, 'error',
                        current=i, video_id=target.video_id,
                        message=result.error,
                    )

                apply_rate_limit(i, total, emit_fn=emit)

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
        job = self._jobs[job_id]
        try:
            def emit(event_type, **data):
                self._emit(job_id, event_type, **data)

            # Pre-filter: remove already-summarized transcripts
            needs_summary = []
            already_done = []
            for rel_path in paths:
                summary_rel = derive_summary_rel_path(rel_path)
                if find_file_recursive(SUMMARIES_DIR, summary_rel):
                    already_done.append(rel_path)
                else:
                    needs_summary.append(rel_path)

            if already_done:
                log.info("Pre-filtered %d already-summarized transcript(s)", len(already_done))
                emit('status', message=f'{len(already_done)} transcript(s) already summarized, skipping.')

            total = len(needs_summary)
            job['total'] = total
            self._emit(job_id, 'total', count=total)

            original_subdirs: set[str] = set()
            for p in needs_summary:
                parent = os.path.dirname(p)
                if parent:
                    original_subdirs.add(parent)

            if total == 0:
                emit('status', message='All selected transcripts are already summarized.')
                self._finish_job(job_id)
                return

            from src.config import get_categorization_config
            auto_categorize = get_categorization_config().get('enabled', False)

            with self._manifest_lock:
                manifest = load_manifest(BASE_DIR)

            for i, rel_path in enumerate(needs_summary, 1):
                self._emit(
                    job_id, 'progress',
                    current=i, total=total,
                    message=f'Summarizing {i}/{total}: {rel_path}',
                )

                with self._manifest_lock:
                    result = process_summary(
                        rel_path, manifest, BASE_DIR, SUMMARIES_DIR,
                        emit_fn=emit,
                    )
                    if result.outcome != 'error':
                        save_manifest(BASE_DIR, manifest)

                if result.outcome == 'skip':
                    # Race-condition safety net — count as success silently
                    job['succeeded'] += 1
                    self._emit(job_id, 'success', current=i, title=rel_path)
                elif result.outcome == 'ok':
                    if auto_categorize:
                        with self._manifest_lock:
                            cat_result = process_categorization(
                                rel_path, result.summary_rel,
                                manifest, BASE_DIR, SUMMARIES_DIR,
                                emit_fn=emit,
                            )
                            if cat_result.outcome == 'ok':
                                save_manifest(BASE_DIR, manifest)
                            elif cat_result.outcome == 'error':
                                log.warning("Categorization failed for %s: %s", rel_path, cat_result.error)
                                self._emit(
                                    job_id, 'warning',
                                    current=i, video_id='',
                                    message=f'Categorization failed: {cat_result.error}',
                                )
                    job['succeeded'] += 1
                    self._emit(job_id, 'success', current=i, title=rel_path)
                else:
                    job['failed'] += 1
                    self._emit(
                        job_id, 'error',
                        current=i, video_id='',
                        message=f'{rel_path}: {result.error}',
                    )

            if auto_categorize and original_subdirs:
                from src.storage import cleanup_empty_subdirs
                removed_t = cleanup_empty_subdirs(BASE_DIR, original_subdirs)
                removed_s = cleanup_empty_subdirs(SUMMARIES_DIR, original_subdirs)
                if removed_t or removed_s:
                    all_removed = sorted(set(removed_t + removed_s))
                    log.info("Cleaned up empty subfolders: %s", ', '.join(all_removed))

        except Exception as e:
            self._emit(job_id, 'error', current=0, video_id='', message=f'Job failed: {e}')

        self._finish_job(job_id)
