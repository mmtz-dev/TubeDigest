"""Chat prompt assembly and per-item conversation history persistence."""

import json
import logging
import os
import tempfile
import threading
import time
from typing import Iterable

from src.storage import CHATS_DIR
from src.summary_storage import derive_summary_rel_path

log = logging.getLogger(__name__)


_TRUNCATION_MARKER = '\n\n[...transcript truncated for length...]\n\n'
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(rel_path: str) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(rel_path)
        if lock is None:
            lock = threading.Lock()
            _locks[rel_path] = lock
        return lock


def _chat_file_path(rel_path: str) -> str:
    return os.path.join(CHATS_DIR, os.path.splitext(rel_path)[0] + '.json')


def load_history(rel_path: str) -> list[dict]:
    """Read stored chat history for an item. Returns [] if no chat file exists."""
    path = _chat_file_path(rel_path)
    if not os.path.isfile(path):
        return []
    with _lock_for(rel_path):
        with open(path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                log.warning("Corrupt chat file %s, ignoring", path)
                return []
    if isinstance(data, list):
        return data
    return []


def append_turns(rel_path: str, new_turns: Iterable[dict]) -> list[dict]:
    """Append turns to an item's chat history atomically. Returns the full updated list."""
    path = _chat_file_path(rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with _lock_for(rel_path):
        existing: list[dict] = []
        if os.path.isfile(path):
            with open(path, 'r', encoding='utf-8') as f:
                try:
                    loaded = json.load(f)
                    if isinstance(loaded, list):
                        existing = loaded
                except json.JSONDecodeError:
                    log.warning("Corrupt chat file %s, starting fresh", path)

        existing.extend(new_turns)

        dir_name = os.path.dirname(path) or '.'
        fd, tmp_path = tempfile.mkstemp(
            prefix='.chat-', suffix='.tmp', dir=dir_name
        )
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    return existing


def _render_history(history: list[dict]) -> str:
    parts = []
    for turn in history:
        role = turn.get('role', 'user')
        content = turn.get('content', '')
        label = 'User' if role == 'user' else 'Assistant'
        parts.append(f'{label}: {content}')
    return '\n\n'.join(parts)


def _truncate_middle(text: str, budget: int) -> str:
    """Keep the first and last halves of `text`, with a marker in the middle, under budget chars."""
    if len(text) <= budget:
        return text
    keep = max(budget - len(_TRUNCATION_MARKER), 0)
    if keep <= 0:
        return _TRUNCATION_MARKER.strip()
    head = keep // 2
    tail = keep - head
    return text[:head] + _TRUNCATION_MARKER + text[-tail:]


def build_chat_prompt(
    summary_text: str | None,
    transcript_text: str,
    history: list[dict],
    user_message: str,
    cfg: dict,
) -> str:
    """Assemble the full prompt string for a chat turn.

    Ordering: system + summary + transcript (stable prefix) | history + user turn (volatile tail).
    Truncates the transcript middle if needed to stay under `max_prompt_chars`.
    """
    system_prompt = cfg.get(
        'system_prompt',
        'You are an expert assistant answering questions about this YouTube video. '
        'Use ONLY the provided summary and transcript. '
        'Say "I don\'t know" if the answer isn\'t there.',
    )
    max_chars = int(cfg.get('max_prompt_chars', 400_000))

    history_block = _render_history(history)
    tail = ''
    if history_block:
        tail += f'\n\n{history_block}'
    tail += f'\n\nUser: {user_message}\n\nAssistant:'

    summary_block = ''
    if summary_text and summary_text.strip():
        summary_block = f'\n\n=== SUMMARY ===\n{summary_text.strip()}\n'
    transcript_block_header = '\n\n=== TRANSCRIPT ===\n'

    fixed_overhead = (
        len(system_prompt) + len(summary_block) + len(transcript_block_header) + len(tail)
    )
    transcript_budget = max(max_chars - fixed_overhead, 1000)
    transcript_rendered = _truncate_middle(transcript_text, transcript_budget)

    return (
        system_prompt
        + summary_block
        + transcript_block_header
        + transcript_rendered
        + tail
    )


def trim_history(history: list[dict], max_turns: int) -> list[dict]:
    """Keep only the most recent `max_turns` turns. A turn = one user or assistant entry."""
    if max_turns <= 0 or len(history) <= max_turns:
        return history
    return history[-max_turns:]


def new_turn(role: str, content: str) -> dict:
    """Build a turn dict with a timestamp."""
    return {'role': role, 'content': content, 'ts': int(time.time())}
