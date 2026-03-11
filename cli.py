#!/usr/bin/env python3
"""CLI for fetching YouTube transcripts and optionally summarizing them."""

import argparse
import os
import random
import sys
import time

from dotenv import load_dotenv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Fetch YouTube transcripts and optionally summarize them.',
        prog='cli.py',
    )
    parser.add_argument(
        'urls',
        nargs='*',
        help='YouTube URLs or video IDs',
    )
    parser.add_argument(
        '--file', '-f',
        metavar='FILE',
        help='Text file with one URL per line',
    )
    parser.add_argument(
        '--output', '-o',
        metavar='DIR',
        help='Output directory for transcripts (default: $TRANSCRIPTIONS_DIR or ./Transcriptions)',
    )
    parser.add_argument(
        '--summaries-dir',
        metavar='DIR',
        help='Output directory for summaries (default: $SUMMARIES_DIR or ./Summaries)',
    )
    parser.add_argument(
        '--summarize', '-s',
        action='store_true',
        help='Generate AI summaries after transcription',
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Reprocess even if already in manifest',
    )
    parser.add_argument(
        '--no-timestamps',
        action='store_true',
        help='Omit timestamps from transcripts',
    )
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Suppress progress output',
    )
    return parser.parse_args()


def collect_urls(args: argparse.Namespace) -> list[str]:
    """Gather URLs from positional args, --file, and stdin."""
    urls = list(args.urls)

    if args.file:
        with open(args.file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    urls.append(line)

    if not sys.stdin.isatty():
        for line in sys.stdin:
            line = line.strip()
            if line and not line.startswith('#'):
                urls.append(line)

    return urls


def log(quiet: bool, message: str) -> None:
    if not quiet:
        print(message)


def derive_summary_rel_path(transcript_rel: str) -> str:
    """Derive the summary .md relative path from a transcript .txt relative path."""
    return os.path.splitext(transcript_rel)[0] + '.md'


def process_single_video(
    video_id: str,
    playlist_name: str | None,
    index: int,
    total: int,
    args: argparse.Namespace,
    transcriptions_dir: str,
    fetch_video_metadata,
    fetch_transcript_auto,
    format_transcript_content,
    save_transcript,
    get_summarization_config,
    summarize,
    save_summary,
    load_manifest,
    save_manifest,
    check_status,
    update_entry,
    manifest: dict,
) -> str:
    """Fetch transcript (and optionally summary) for one video. Returns outcome: 'ok', 'skip', 'error'."""
    quiet = args.quiet
    include_timestamps = not args.no_timestamps
    prefix = f'[{index}/{total}]'

    status = 'needs_transcript' if args.force else check_status(
        manifest, video_id, transcriptions_dir, args._summaries_dir
    )

    if status == 'skip':
        entry = manifest[video_id]
        log(quiet, f'{prefix} Skipped (already processed): "{entry["title"]}"')
        return 'skip'

    # -- Transcript phase --
    if status == 'needs_transcript':
        try:
            metadata = fetch_video_metadata(video_id)
            title = metadata['title']
            log(quiet, f'{prefix} Fetching: "{title}"...')

            transcript, _method = fetch_transcript_auto(
                video_id,
                metadata.get('duration'),
                include_timestamps=include_timestamps,
            )
            content = format_transcript_content(title, video_id, transcript, include_timestamps)
            filepath = save_transcript(title, video_id, content, playlist_name)
            transcript_rel = os.path.relpath(filepath, transcriptions_dir)

            update_entry(manifest, video_id, title, transcript_rel, None)
            save_manifest(transcriptions_dir, manifest)

        except Exception as exc:
            title = video_id
            log(quiet, f'{prefix} ERROR: "{title}" — {exc}')
            return 'error'
    else:
        # needs_summary — transcript already exists
        title = manifest[video_id]['title']
        transcript_rel = manifest[video_id]['transcript']

    # -- Summary phase --
    if args.summarize:
        log(quiet, f'{prefix} Summarizing: "{title}"...')
        try:
            transcript_full_path = os.path.join(transcriptions_dir, transcript_rel)
            with open(transcript_full_path, 'r', encoding='utf-8') as f:
                transcript_text = f.read()

            cfg = get_summarization_config()
            summary_text, provider = summarize(transcript_text, cfg)

            save_summary(transcript_rel, summary_text, provider)
            summary_rel = derive_summary_rel_path(transcript_rel)

            update_entry(manifest, video_id, title, transcript_rel, summary_rel)
            save_manifest(transcriptions_dir, manifest)

        except Exception as exc:
            log(quiet, f'{prefix} ERROR summarizing "{title}" — {exc}')
            return 'error'

    log(quiet, f'{prefix} Done: "{title}"')
    return 'ok'


def expand_playlists(
    raw_urls: list[str],
    quiet: bool,
    extract_video_id,
    is_playlist_url,
    extract_playlist_videos,
) -> list[tuple[str, str | None]]:
    """Expand raw URLs into (video_id, playlist_name | None) tuples."""
    expanded: list[tuple[str, str | None]] = []

    for url in raw_urls:
        if is_playlist_url(url):
            log(quiet, f'Expanding playlist: {url}')
            try:
                playlist = extract_playlist_videos(url)
                playlist_name = playlist['title']
                for video in playlist['videos']:
                    expanded.append((video['video_id'], playlist_name))
                log(quiet, f'  Found {len(playlist["videos"])} videos in "{playlist_name}"')
            except Exception as exc:
                print(f'ERROR expanding playlist {url}: {exc}', file=sys.stderr)
        else:
            video_id = extract_video_id(url)
            if video_id:
                expanded.append((video_id, None))
            else:
                print(f'WARNING: Could not extract video ID from: {url}', file=sys.stderr)

    return expanded


def main() -> None:
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    load_dotenv(_env_path)

    args = parse_args()

    if args.output:
        os.environ['TRANSCRIPTIONS_DIR'] = os.path.abspath(args.output)
    if args.summaries_dir:
        os.environ['SUMMARIES_DIR'] = os.path.abspath(args.summaries_dir)

    # Late imports so the env vars set above take effect in module-level constants
    from src.fetcher import extract_video_id, fetch_video_metadata, fetch_transcript_auto
    from src.playlist import is_playlist_url, extract_playlist_videos
    from src.storage import format_transcript_content, save_transcript, BASE_DIR
    from src.config import get_summarization_config
    from src.summarizer import summarize
    from src.summary_storage import save_summary, SUMMARIES_DIR
    from src.manifest import load_manifest, save_manifest, check_status, update_entry

    transcriptions_dir: str = BASE_DIR
    summaries_dir: str = SUMMARIES_DIR
    # Attach resolved dirs to args so helpers can access them without extra params
    args._summaries_dir = summaries_dir

    raw_urls = collect_urls(args)
    if not raw_urls:
        print('Error: no URLs provided. Pass URLs as arguments, --file, or via stdin.', file=sys.stderr)
        sys.exit(1)

    videos = expand_playlists(
        raw_urls,
        args.quiet,
        extract_video_id,
        is_playlist_url,
        extract_playlist_videos,
    )

    if not videos:
        print('Error: no valid video IDs found.', file=sys.stderr)
        sys.exit(1)

    os.makedirs(transcriptions_dir, exist_ok=True)
    manifest = load_manifest(transcriptions_dir)

    total = len(videos)
    succeeded = skipped = failed = 0

    for i, (video_id, playlist_name) in enumerate(videos, start=1):
        outcome = process_single_video(
            video_id=video_id,
            playlist_name=playlist_name,
            index=i,
            total=total,
            args=args,
            transcriptions_dir=transcriptions_dir,
            fetch_video_metadata=fetch_video_metadata,
            fetch_transcript_auto=fetch_transcript_auto,
            format_transcript_content=format_transcript_content,
            save_transcript=save_transcript,
            get_summarization_config=get_summarization_config,
            summarize=summarize,
            save_summary=save_summary,
            load_manifest=load_manifest,
            save_manifest=save_manifest,
            check_status=check_status,
            update_entry=update_entry,
            manifest=manifest,
        )

        if outcome == 'ok':
            succeeded += 1
        elif outcome == 'skip':
            skipped += 1
        else:
            failed += 1

        # Rate limiting between videos in a batch
        if i < total:
            if i % 10 == 0:
                time.sleep(15)
            else:
                time.sleep(random.uniform(2, 5))

    log(args.quiet, f'Done! {succeeded} succeeded, {skipped} skipped, {failed} failed')

    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
