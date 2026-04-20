"""Category-level chat: prompt assembly with summaries + keyword-retrieved transcripts."""

import logging
import os
import re
from typing import Iterable

from src.chat import (
    _lock_for,
    new_turn,
    trim_history,
    _TRUNCATION_MARKER,
)
from src.storage import CHATS_DIR
from src.summary_storage import (
    canonical_category_key,
    list_transcripts,
    read_summary,
    read_transcript,
)

log = logging.getLogger(__name__)


CATEGORY_CHATS_SUBDIR = '_categories'

_STOPWORDS = {
    'a', 'about', 'above', 'after', 'again', 'against', 'all', 'am', 'an', 'and',
    'any', 'are', 'as', 'at', 'be', 'because', 'been', 'before', 'being', 'below',
    'between', 'both', 'but', 'by', 'could', 'did', 'do', 'does', 'doing', 'down',
    'during', 'each', 'few', 'for', 'from', 'further', 'had', 'has', 'have',
    'having', 'he', 'her', 'here', 'hers', 'herself', 'him', 'himself', 'his',
    'how', 'i', 'if', 'in', 'into', 'is', 'it', 'its', 'itself', 'just', 'me',
    'more', 'most', 'my', 'myself', 'no', 'nor', 'not', 'now', 'of', 'off', 'on',
    'once', 'only', 'or', 'other', 'our', 'ours', 'ourselves', 'out', 'over',
    'own', 'same', 'she', 'should', 'so', 'some', 'such', 'than', 'that', 'the',
    'their', 'theirs', 'them', 'themselves', 'then', 'there', 'these', 'they',
    'this', 'those', 'through', 'to', 'too', 'under', 'until', 'up', 'very',
    'was', 'we', 'were', 'what', 'when', 'where', 'which', 'while', 'who',
    'whom', 'why', 'will', 'with', 'would', 'you', 'your', 'yours', 'yourself',
    'yourselves', 'video', 'videos', 'tell', 'give', 'say', 'said',
}


def _chat_file_path(key: str) -> str:
    return os.path.join(CHATS_DIR, CATEGORY_CHATS_SUBDIR, f'{key}.json')


def category_items(key: str) -> list[dict]:
    """Return all transcripts whose canonical category matches `key` (newest first)."""
    target = (key or '').strip().lower()
    return [t for t in list_transcripts() if t['category_key'] == target]


def load_history(key: str) -> list[dict]:
    import json
    path = _chat_file_path(key)
    if not os.path.isfile(path):
        return []
    with _lock_for(f'_cat:{key}'):
        with open(path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                log.warning("Corrupt category-chat file %s, ignoring", path)
                return []
    return data if isinstance(data, list) else []


def append_turns(key: str, new_turns: Iterable[dict]) -> list[dict]:
    import json
    import tempfile

    path = _chat_file_path(key)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with _lock_for(f'_cat:{key}'):
        existing: list[dict] = []
        if os.path.isfile(path):
            with open(path, 'r', encoding='utf-8') as f:
                try:
                    loaded = json.load(f)
                    if isinstance(loaded, list):
                        existing = loaded
                except json.JSONDecodeError:
                    log.warning("Corrupt category-chat file %s, starting fresh", path)

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


def _extract_query_terms(message: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", message.lower())
    return [w for w in words if w not in _STOPWORDS]


def _score_transcript(terms: list[str], text_lower: str) -> int:
    """Unique-term hit count. Prefers broad keyword coverage over frequency."""
    if not terms:
        return 0
    return sum(1 for t in set(terms) if t in text_lower)


def pick_relevant_transcripts(
    user_message: str,
    items: list[dict],
    budget_chars: int,
    max_items: int = 3,
    min_score: int = 2,
) -> list[tuple[dict, str]]:
    """Retrieve the most topically relevant transcripts for this turn.

    Scores each item's transcript by how many unique query terms it contains.
    Returns up to `max_items` (item, text) pairs whose score >= `min_score`,
    trimmed so their combined size fits `budget_chars`. The last included
    transcript may be middle-truncated.
    """
    terms = _extract_query_terms(user_message)
    if not terms or budget_chars <= 0 or not items:
        return []

    scored: list[tuple[int, dict, str]] = []
    for item in items:
        try:
            text = read_transcript(item['path'])
        except FileNotFoundError:
            continue
        score = _score_transcript(terms, text.lower())
        if score >= min_score:
            scored.append((score, item, text))

    scored.sort(key=lambda s: (-s[0], -item_mtime(s[1])))

    selected: list[tuple[dict, str]] = []
    remaining = budget_chars
    for score, item, text in scored[:max_items]:
        if remaining <= 500:
            break
        if len(text) <= remaining:
            selected.append((item, text))
            remaining -= len(text)
        else:
            selected.append((item, _truncate_middle(text, remaining)))
            remaining = 0
            break

    return selected


def item_mtime(item: dict) -> float:
    return float(item.get('mtime') or 0)


def _truncate_middle(text: str, budget: int) -> str:
    if len(text) <= budget:
        return text
    keep = max(budget - len(_TRUNCATION_MARKER), 0)
    if keep <= 0:
        return _TRUNCATION_MARKER.strip()
    head = keep // 2
    tail = keep - head
    return text[:head] + _TRUNCATION_MARKER + text[-tail:]


def _render_history(history: list[dict]) -> str:
    parts = []
    for turn in history:
        role = turn.get('role', 'user')
        content = turn.get('content', '')
        label = 'User' if role == 'user' else 'Assistant'
        parts.append(f'{label}: {content}')
    return '\n\n'.join(parts)


def build_category_chat_prompt(
    display_name: str,
    items: list[dict],
    history: list[dict],
    user_message: str,
    cfg: dict,
) -> tuple[str, list[dict]]:
    """Assemble a prompt about a whole category.

    Strategy:
      1. Always include the category's item list and every item's summary
         (falls back to filename when no summary exists).
      2. Keyword-retrieve the top transcripts for this turn and include them
         after summaries if the prompt budget allows.

    Returns (prompt_string, retrieved_items_for_ui) so the UI can show which
    items were pulled in for this turn.
    """
    system_prompt = cfg.get(
        'category_system_prompt',
        'You are an expert assistant answering questions about a collection of '
        'YouTube videos grouped under the category below. Ground answers in the '
        'provided summaries and any included transcripts. When you cite a video, '
        'name it so the user can open it. Say "I don\'t know" if the answer '
        "isn't in the provided materials.",
    )
    max_chars = int(cfg.get('max_prompt_chars', 400_000))

    header = f'\n\n=== CATEGORY: {display_name} ({len(items)} items) ===\n'

    summaries_parts = []
    for idx, item in enumerate(items, 1):
        summary = read_summary(item['path'])
        label = f'[{idx}] {item["filename"]}'
        if summary:
            summaries_parts.append(f'{label}\n{summary.strip()}')
        else:
            summaries_parts.append(f'{label}\n(no summary — transcript only)')
    summaries_block = '\n\n=== SUMMARIES ===\n' + '\n\n---\n\n'.join(summaries_parts)

    history_block = _render_history(history)
    tail = ''
    if history_block:
        tail += f'\n\n{history_block}'
    tail += f'\n\nUser: {user_message}\n\nAssistant:'

    fixed = len(system_prompt) + len(header) + len(summaries_block) + len(tail)
    retrieval_budget = max(max_chars - fixed, 0)

    retrieved = pick_relevant_transcripts(user_message, items, retrieval_budget)
    retrieved_block = ''
    if retrieved:
        pieces = []
        for item, text in retrieved:
            pieces.append(f'--- {item["filename"]} ---\n{text}')
        retrieved_block = '\n\n=== RELEVANT TRANSCRIPTS (selected for this question) ===\n' + '\n\n'.join(pieces)

    prompt = system_prompt + header + summaries_block + retrieved_block + tail
    retrieved_info = [
        {'path': item['path'], 'filename': item['filename']}
        for item, _ in retrieved
    ]
    return prompt, retrieved_info
