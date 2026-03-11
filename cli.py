#!/usr/bin/env python3
"""CLI for fetching YouTube transcripts and optionally summarizing them."""

import argparse
import os
import sys

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


def main() -> None:
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    load_dotenv(_env_path)

    args = parse_args()

    if args.output:
        os.environ['TRANSCRIPTIONS_DIR'] = os.path.abspath(args.output)
    if args.summaries_dir:
        os.environ['SUMMARIES_DIR'] = os.path.abspath(args.summaries_dir)

    # Late imports so the env vars set above take effect in module-level constants
    from src.manifest import load_manifest, save_manifest
    from src.pipeline import expand_urls, process_video, process_summary, apply_rate_limit
    from src.storage import TRANSCRIPTIONS_DIR, SUMMARIES_DIR

    transcriptions_dir = TRANSCRIPTIONS_DIR
    summaries_dir = SUMMARIES_DIR

    raw_urls = collect_urls(args)
    if not raw_urls:
        print('Error: no URLs provided. Pass URLs as arguments, --file, or via stdin.', file=sys.stderr)
        sys.exit(1)

    quiet = args.quiet

    def emit(event_type, **data):
        if event_type == 'error':
            print(f'ERROR: {data.get("message", "")}', file=sys.stderr)
        elif event_type == 'warning':
            print(f'WARNING: {data.get("message", "")}', file=sys.stderr)
        elif not quiet:
            msg = data.get('message', '')
            if msg:
                print(msg)

    videos = expand_urls(raw_urls, emit_fn=emit)

    if not videos:
        print('Error: no valid video IDs found.', file=sys.stderr)
        sys.exit(1)

    os.makedirs(transcriptions_dir, exist_ok=True)
    manifest = load_manifest(transcriptions_dir)

    total = len(videos)
    succeeded = skipped = failed = 0
    include_timestamps = not args.no_timestamps

    for i, target in enumerate(videos, start=1):
        prefix = f'[{i}/{total}]'

        result = process_video(
            target.video_id, target.playlist_name,
            manifest, transcriptions_dir, summaries_dir,
            include_timestamps=include_timestamps,
            force=args.force,
            emit_fn=emit,
        )

        if result.outcome == 'skip':
            log(quiet, f'{prefix} Skipped (already processed): "{result.title}"')
            skipped += 1
        elif result.outcome == 'error':
            log(quiet, f'{prefix} ERROR: "{result.title}" — {result.error}')
            failed += 1
        else:
            save_manifest(transcriptions_dir, manifest)

            if args.summarize:
                log(quiet, f'{prefix} Summarizing: "{result.title}"...')
                sr = process_summary(
                    result.transcript_rel, manifest,
                    transcriptions_dir, summaries_dir,
                    emit_fn=emit,
                )
                if sr.outcome == 'error':
                    log(quiet, f'{prefix} ERROR summarizing "{result.title}" — {sr.error}')
                    failed += 1
                    continue
                save_manifest(transcriptions_dir, manifest)

            log(quiet, f'{prefix} Done: "{result.title}"')
            succeeded += 1

        apply_rate_limit(i, total, emit_fn=emit)

    log(quiet, f'Done! {succeeded} succeeded, {skipped} skipped, {failed} failed')

    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
