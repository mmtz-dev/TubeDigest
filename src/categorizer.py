"""AI-powered auto-categorization of transcripts and summaries."""

import logging
import os
import shutil

from src.storage import sanitize_filename

log = logging.getLogger(__name__)

CATEGORIZATION_PROMPT_WITH_EXISTING = """\
You are a categorization assistant. Given a video title and its summary, \
assign it to the single most appropriate category.

Existing categories:
{categories}

Rules:
- Prefer reusing an existing category if it fits well
- If none fit, create a new one
- Reply with ONLY the category name, nothing else
- Use Title Case
- 1-3 words maximum
- No punctuation or special characters"""

CATEGORIZATION_PROMPT_NO_EXISTING = """\
You are a categorization assistant. Given a video title and its summary, \
assign it to the single most appropriate category.

Rules:
- Reply with ONLY the category name, nothing else
- Use Title Case
- 1-3 words maximum
- No punctuation or special characters"""


def scan_existing_categories(transcriptions_dir: str) -> list[str]:
    """List top-level category directories in the transcriptions folder."""
    if not os.path.isdir(transcriptions_dir):
        return []

    categories = []
    for entry in os.scandir(transcriptions_dir):
        if entry.is_dir() and not entry.name.startswith('.'):
            categories.append(entry.name)

    return sorted(categories)


def categorize(
    summary_text: str,
    video_title: str,
    existing_categories: list[str],
    cfg: dict,
    emit_fn=None,
) -> str:
    """Use AI to assign a category based on the summary and title.

    Reuses the summarization provider chain with a categorization-specific prompt.
    Returns the category name (sanitized).
    """
    from src.config import get_summarization_config
    from src.summarizer import summarize

    emit = emit_fn or (lambda *a, **kw: None)

    if existing_categories:
        prompt = CATEGORIZATION_PROMPT_WITH_EXISTING.format(
            categories='\n'.join(f'- {c}' for c in existing_categories)
        )
    else:
        prompt = CATEGORIZATION_PROMPT_NO_EXISTING

    # Feed the title + summary as the "transcript" input to the summarizer
    input_text = f"Title: {video_title}\n\nSummary:\n{summary_text}"

    sum_cfg = get_summarization_config()
    # Override the prompt for categorization
    cat_cfg = {**sum_cfg, 'prompt': prompt}

    emit('status', message='Categorizing...')
    raw_category, provider = summarize(input_text, cat_cfg, emit_fn=emit)

    # Parse: strip whitespace, quotes, markdown formatting, take first line
    category = raw_category.strip().strip('"\'`').strip()
    category = category.split('\n')[0].strip()
    # Remove any markdown bold/italic
    category = category.replace('**', '').replace('*', '').replace('`', '')

    # Sanitize and cap length
    category = sanitize_filename(category)
    if len(category) > 50:
        category = category[:50].rstrip('_')

    if not category:
        category = 'Uncategorized'

    log.info("AI categorized as: %s (provider: %s)", category, provider)
    return category


def move_to_category(
    transcript_rel: str,
    summary_rel: str,
    category: str,
    transcriptions_dir: str,
    summaries_dir: str,
) -> tuple[str, str]:
    """Move transcript and summary files into category subfolders.

    Returns (new_transcript_rel, new_summary_rel).
    No-op if files are already in the target category folder.
    """
    transcript_basename = os.path.basename(transcript_rel)
    summary_basename = os.path.basename(summary_rel)

    new_transcript_rel = os.path.join(category, transcript_basename)
    new_summary_rel = os.path.join(category, summary_basename)

    # No-op if already in the right folder
    if os.path.normpath(transcript_rel) == os.path.normpath(new_transcript_rel):
        return transcript_rel, summary_rel

    # Create category directories
    transcript_cat_dir = os.path.join(transcriptions_dir, category)
    summary_cat_dir = os.path.join(summaries_dir, category)
    os.makedirs(transcript_cat_dir, exist_ok=True)
    os.makedirs(summary_cat_dir, exist_ok=True)

    # Handle duplicate filenames
    new_transcript_rel = _deduplicate(new_transcript_rel, transcriptions_dir)
    new_summary_rel = _deduplicate(new_summary_rel, summaries_dir)

    src_transcript = os.path.join(transcriptions_dir, transcript_rel)
    dst_transcript = os.path.join(transcriptions_dir, new_transcript_rel)
    src_summary = os.path.join(summaries_dir, summary_rel)
    dst_summary = os.path.join(summaries_dir, new_summary_rel)

    # Move transcript first
    if os.path.isfile(src_transcript):
        shutil.move(src_transcript, dst_transcript)
    else:
        log.warning("Transcript file not found for move: %s", src_transcript)
        return transcript_rel, summary_rel

    # Move summary; rollback transcript if this fails
    if os.path.isfile(src_summary):
        try:
            shutil.move(src_summary, dst_summary)
        except Exception:
            # Rollback transcript move
            shutil.move(dst_transcript, src_transcript)
            raise
    else:
        log.warning("Summary file not found for move: %s", src_summary)
        # Rollback transcript move
        shutil.move(dst_transcript, src_transcript)
        return transcript_rel, summary_rel

    return new_transcript_rel, new_summary_rel


def _deduplicate(rel_path: str, base_dir: str) -> str:
    """If the target path already exists, append _2, _3, etc. before the extension."""
    full = os.path.join(base_dir, rel_path)
    if not os.path.exists(full):
        return rel_path

    stem, ext = os.path.splitext(rel_path)
    counter = 2
    while True:
        candidate = f"{stem}_{counter}{ext}"
        if not os.path.exists(os.path.join(base_dir, candidate)):
            return candidate
        counter += 1
