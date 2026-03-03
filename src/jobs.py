"""Background job manager with threading and queue-based progress reporting."""

import json
import random
import threading
import time
import uuid
from queue import Queue

from src.fetcher import extract_video_id, fetch_video_metadata, fetch_transcript
from src.playlist import is_playlist_url, extract_playlist_videos
from src.storage import format_transcript_content, save_transcript


class JobManager:
    """Manages background transcript-fetching jobs."""

    def __init__(self):
        self._jobs: dict[str, dict] = {}

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

            for i, video in enumerate(videos, 1):
                video_id = video['video_id']
                playlist_name = video.get('playlist_name')
                self._emit(
                    job_id, 'progress',
                    current=i, total=total,
                    message=f'Processing video {i}/{total}: {video_id}',
                )
                try:
                    metadata = fetch_video_metadata(video_id)
                    title = metadata['title']

                    self._emit(
                        job_id, 'status',
                        message=f'Fetching transcript for: {title}',
                    )
                    transcript = fetch_transcript(video_id, include_timestamps)
                    content = format_transcript_content(title, video_id, transcript, include_timestamps)
                    save_transcript(title, video_id, content, playlist_name)

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
