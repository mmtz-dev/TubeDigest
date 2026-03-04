"""Flask entry point with routes and SSE streaming."""

import json
import logging
import os
import subprocess
import time
from queue import Empty

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, Response, jsonify, render_template, request

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
)

from src.jobs import JobManager
from src.storage import BASE_DIR as TRANSCRIPTIONS_DIR
from src.summary_storage import list_transcripts, SUMMARIES_DIR

app = Flask(__name__)
job_manager = JobManager()

IN_DOCKER = os.environ.get('RUNNING_IN_DOCKER', '').lower() == 'true'


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


@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'})


@app.route('/api/open-folder', methods=['POST'])
def open_folder():
    if IN_DOCKER:
        return jsonify({'error': 'Cannot open folder from inside Docker container', 'path': TRANSCRIPTIONS_DIR}), 400

    os.makedirs(TRANSCRIPTIONS_DIR, exist_ok=True)
    try:
        subprocess.Popen(['xdg-open', TRANSCRIPTIONS_DIR])
        return jsonify({'ok': True})
    except FileNotFoundError:
        return jsonify({'error': 'xdg-open not available', 'path': TRANSCRIPTIONS_DIR}), 500


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
        if '..' in p or p.startswith('/'):
            return jsonify({'error': f'Invalid path: {p}'}), 400

    job_id = job_manager.create_summarization_job(paths)
    return jsonify({'job_id': job_id})


@app.route('/api/summaries/<path:rel_path>')
def get_summary(rel_path):
    if '..' in rel_path or rel_path.startswith('/'):
        return jsonify({'error': 'Invalid path'}), 400

    # Summary files use .md extension
    md_path = os.path.splitext(rel_path)[0] + '.md'
    full_path = os.path.join(SUMMARIES_DIR, md_path)
    if not os.path.isfile(full_path):
        return jsonify({'error': 'Summary not found'}), 404

    with open(full_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return jsonify({'content': content})


@app.route('/api/open-summaries-folder', methods=['POST'])
def open_summaries_folder():
    if IN_DOCKER:
        return jsonify({'error': 'Cannot open folder from inside Docker container', 'path': SUMMARIES_DIR}), 400

    os.makedirs(SUMMARIES_DIR, exist_ok=True)
    try:
        subprocess.Popen(['xdg-open', SUMMARIES_DIR])
        return jsonify({'ok': True})
    except FileNotFoundError:
        return jsonify({'error': 'xdg-open not available', 'path': SUMMARIES_DIR}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5555))
    app.run(debug=True, host='0.0.0.0', port=port, threaded=True)
