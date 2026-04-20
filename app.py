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
from src.storage import TRANSCRIPTIONS_DIR, SUMMARIES_DIR, CHATS_DIR
from src.summary_storage import (
    list_transcripts,
    list_categories_with_counts,
    derive_summary_rel_path,
    read_summary,
    read_transcript,
    validate_rel_path,
)
from src.config import get_transcription_config, get_chat_config
from src.usage_tracker import get_yt_api_count
from src.ytdlp_tracker import get_ytdlp_count
from src import chat as chat_module
from src import category_chat as category_chat_module
from src.summarizer import run_providers

app = Flask(__name__)
job_manager = JobManager()

log = logging.getLogger(__name__)


def log_startup_info():
    log.info("Transcriptions directory: %s", TRANSCRIPTIONS_DIR)
    log.info("Summaries directory:      %s", SUMMARIES_DIR)
    log.info("Chats directory:          %s", CHATS_DIR)
    log.info("Today's YT API transcript count: %d", get_yt_api_count())
    log.info("Today's yt-dlp usage count:      %d", get_ytdlp_count())


log_startup_info()


def format_sse(data: dict) -> str:
    """Format a dict as an SSE message."""
    return f"data: {json.dumps(data)}\n\n"


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/explore')
def explore():
    return render_template('explore.html')


@app.route('/categories')
def categories_page():
    return render_template('categories.html')


@app.route('/api/categories')
def get_categories():
    return jsonify({'categories': list_categories_with_counts()})


@app.route('/feed')
def feed_page():
    return render_template('feed.html')


def _find_category(key: str):
    key_norm = (key or '').strip().lower()
    for cat in list_categories_with_counts():
        if cat['key'] == key_norm:
            return cat
    return None


@app.route('/chat/category/<key>')
def category_chat_page(key):
    cat = _find_category(key)
    if not cat:
        return "Category not found", 404
    return render_template('category_chat.html', category_key=cat['key'], category_display=cat['display'])


@app.route('/api/category/<key>')
def get_category(key):
    cat = _find_category(key)
    if not cat:
        return jsonify({'error': 'Category not found'}), 404
    items = category_chat_module.category_items(cat['key'])
    history = category_chat_module.load_history(cat['key'])
    return jsonify({
        'key': cat['key'],
        'display': cat['display'],
        'folders': cat['folders'],
        'count': cat['count'],
        'summarized_count': cat['summarized_count'],
        'items': items,
        'history': history,
    })


@app.route('/api/category_chat', methods=['POST'])
def category_chat_turn():
    body = request.get_json(force=True)
    key = (body.get('key') or '').strip().lower()
    message = (body.get('message') or '').strip()

    cat = _find_category(key)
    if not cat:
        return jsonify({'error': 'Category not found'}), 404
    if not message:
        return jsonify({'error': 'Empty message'}), 400

    items = category_chat_module.category_items(cat['key'])
    cfg = get_chat_config()
    history = category_chat_module.load_history(cat['key'])
    trimmed = chat_module.trim_history(history, int(cfg.get('max_history_turns', 20)))

    prompt, retrieved = category_chat_module.build_category_chat_prompt(
        cat['display'], items, trimmed, message, cfg,
    )

    try:
        reply, provider = run_providers(prompt, cfg)
    except RuntimeError as e:
        log.error("Category chat generation failed for %s: %s", cat['key'], e)
        return jsonify({'error': str(e)}), 502

    user_turn = chat_module.new_turn('user', message)
    assistant_turn = chat_module.new_turn('assistant', reply)
    assistant_turn['provider'] = provider
    if retrieved:
        assistant_turn['retrieved'] = retrieved
    category_chat_module.append_turns(cat['key'], [user_turn, assistant_turn])

    return jsonify({'reply': reply, 'provider': provider, 'retrieved': retrieved})


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
    chats_display = os.environ.get('HOST_CHATS_DIR', CHATS_DIR)
    return jsonify({
        'transcriptions_dir': transcriptions_display,
        'summaries_dir': summaries_display,
        'chats_dir': chats_display,
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

    for p in paths:
        if not validate_rel_path(p):
            return jsonify({'error': f'Invalid path: {p}'}), 400

    job_id = job_manager.create_summarization_job(paths)
    return jsonify({'job_id': job_id})


@app.route('/api/summaries/<path:rel_path>')
def get_summary(rel_path):
    if not validate_rel_path(rel_path):
        return jsonify({'error': 'Invalid path'}), 400

    # Summary files use .md extension
    full_path = os.path.join(SUMMARIES_DIR, derive_summary_rel_path(rel_path))
    if not os.path.isfile(full_path):
        return jsonify({'error': 'Summary not found'}), 404

    with open(full_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return jsonify({'content': content})


@app.route('/chat/<path:rel_path>')
def chat_page(rel_path):
    if not validate_rel_path(rel_path):
        return "Invalid path", 400
    full_path = os.path.join(TRANSCRIPTIONS_DIR, rel_path)
    if not os.path.isfile(full_path):
        return "Transcript not found", 404
    return render_template('chat.html', rel_path=rel_path)


@app.route('/api/item/<path:rel_path>')
def get_item(rel_path):
    if not validate_rel_path(rel_path):
        return jsonify({'error': 'Invalid path'}), 400
    try:
        transcript = read_transcript(rel_path)
    except FileNotFoundError:
        return jsonify({'error': 'Transcript not found'}), 404

    summary = read_summary(rel_path)
    history = chat_module.load_history(rel_path)
    return jsonify({
        'path': rel_path,
        'filename': os.path.basename(rel_path),
        'subfolder': os.path.dirname(rel_path),
        'transcript': transcript,
        'summary': summary,
        'history': history,
    })


@app.route('/api/chat', methods=['POST'])
def chat_turn():
    body = request.get_json(force=True)
    rel_path = body.get('path', '')
    message = (body.get('message') or '').strip()

    if not validate_rel_path(rel_path):
        return jsonify({'error': 'Invalid path'}), 400
    if not message:
        return jsonify({'error': 'Empty message'}), 400

    try:
        transcript = read_transcript(rel_path)
    except FileNotFoundError:
        return jsonify({'error': 'Transcript not found'}), 404

    summary = read_summary(rel_path)
    cfg = get_chat_config()
    history = chat_module.load_history(rel_path)
    trimmed = chat_module.trim_history(history, int(cfg.get('max_history_turns', 20)))

    prompt = chat_module.build_chat_prompt(summary, transcript, trimmed, message, cfg)

    try:
        reply, provider = run_providers(prompt, cfg)
    except RuntimeError as e:
        log.error("Chat generation failed for %s: %s", rel_path, e)
        return jsonify({'error': str(e)}), 502

    user_turn = chat_module.new_turn('user', message)
    assistant_turn = chat_module.new_turn('assistant', reply)
    assistant_turn['provider'] = provider
    chat_module.append_turns(rel_path, [user_turn, assistant_turn])

    return jsonify({'reply': reply, 'provider': provider})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5555))
    app.run(debug=True, host='0.0.0.0', port=port, threaded=True)
