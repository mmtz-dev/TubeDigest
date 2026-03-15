"""Flask entry point with routes and SSE streaming."""

import json
import logging
import os
import time
from queue import Empty

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

from flask import Flask, Response, jsonify, render_template, request

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
)

from src.jobs import JobManager
from src.storage import TRANSCRIPTIONS_DIR, SUMMARIES_DIR
from src.summary_storage import list_transcripts, derive_summary_rel_path
from src.config import get_transcription_config
from src.usage_tracker import get_yt_api_count
from src.ytdlp_tracker import get_ytdlp_count

app = Flask(__name__)
job_manager = JobManager()

log = logging.getLogger(__name__)


def log_startup_info():
    log.info("Transcriptions directory: %s", TRANSCRIPTIONS_DIR)
    log.info("Summaries directory:      %s", SUMMARIES_DIR)
    log.info("Today's YT API transcript count: %d", get_yt_api_count())
    log.info("Today's yt-dlp usage count:      %d", get_ytdlp_count())


log_startup_info()


def format_sse(data: dict) -> str:
    """Format a dict as an SSE message."""
    return f"data: {json.dumps(data)}\n\n"


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/start', methods=['POST'])
def start_job():
    body = request.get_json(force=True)
    raw_urls = body.get('urls', '')
    include_timestamps = body.get('include_timestamps', True)

    if isinstance(raw_urls, str):
        urls = [u.strip() for u in raw_urls.splitlines() if u.strip()]
    else:
        urls = raw_urls

    if not urls:
        return jsonify({'error': 'No URLs provided'}), 400

    job_id = job_manager.create_job(urls, include_timestamps)
    return jsonify({'job_id': job_id})


@app.route('/api/progress/<job_id>')
def progress(job_id):
    queue = job_manager.get_queue(job_id)
    if queue is None:
        return jsonify({'error': 'Job not found'}), 404

    def stream():
        last_keepalive = time.time()
        while True:
            try:
                msg = queue.get(timeout=1)
                yield format_sse(msg)
                if msg.get('type') == 'done':
                    break
            except Empty:
                # Send keepalive comment every 30s
                if time.time() - last_keepalive > 30:
                    yield ": keepalive\n\n"
                    last_keepalive = time.time()

    return Response(stream(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
    })


@app.route('/api/jobs/<job_id>')
def job_status(job_id):
    status = job_manager.get_status(job_id)
    if status is None:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify(status)


@app.route('/api/info')
def app_info():
    cfg = get_transcription_config()
    # Show host paths when running in Docker, otherwise show the actual paths
    transcriptions_display = os.environ.get('HOST_TRANSCRIPTIONS_DIR', TRANSCRIPTIONS_DIR)
    summaries_display = os.environ.get('HOST_SUMMARIES_DIR', SUMMARIES_DIR)
    return jsonify({
        'transcriptions_dir': transcriptions_display,
        'summaries_dir': summaries_display,
        'yt_api_count': get_yt_api_count(),
        'yt_api_daily_limit': cfg['yt_api_daily_limit'],
        'ytdlp_count': get_ytdlp_count(),
        'ytdlp_daily_limit': cfg['ytdlp_daily_limit'],
    })


@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'})


@app.route('/api/transcripts')
def get_transcripts():
    return jsonify({'transcripts': list_transcripts()})


@app.route('/api/summarize', methods=['POST'])
def start_summarize():
    body = request.get_json(force=True)
    paths = body.get('paths', [])

    if not paths:
        return jsonify({'error': 'No transcript paths provided'}), 400

    # Validate paths: no directory traversal or absolute paths
    for p in paths:
        if os.sep + '..' in p or p.startswith('..') or os.path.isabs(p):
            return jsonify({'error': f'Invalid path: {p}'}), 400

    job_id = job_manager.create_summarization_job(paths)
    return jsonify({'job_id': job_id})


@app.route('/api/summaries/<path:rel_path>')
def get_summary(rel_path):
    if os.sep + '..' in rel_path or rel_path.startswith('..') or os.path.isabs(rel_path):
        return jsonify({'error': 'Invalid path'}), 400

    # Summary files use .md extension
    full_path = os.path.join(SUMMARIES_DIR, derive_summary_rel_path(rel_path))
    if not os.path.isfile(full_path):
        return jsonify({'error': 'Summary not found'}), 404

    with open(full_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return jsonify({'content': content})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5555))
    app.run(debug=True, host='0.0.0.0', port=port, threaded=True)
