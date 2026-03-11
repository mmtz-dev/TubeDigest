# TubeDigest

A local tool that downloads YouTube transcripts and summarizes them with AI. Supports individual videos, Shorts, and full playlists. Available as a **web app** or **CLI**.

## Quick Start (macOS with Docker)

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/)
2. Double-click `start.command`

That's it — Docker starts, the app builds, and your browser opens to `http://localhost:5555`.

To stop, double-click `stop.command`.

## Quick Start (Docker Compose)

```bash
cp .env.example .env        # create config, add API keys
docker compose up --build -d # build and start
```

Open `http://localhost:5555`. Stop with `docker compose down`.

## Quick Start (Local Python)

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Requires Python 3.12+ and FFmpeg (for Whisper fallback).

## CLI Usage

The CLI lets you fetch transcripts and summaries from the command line without starting the web server.

```bash
source .venv/bin/activate

# Transcribe a single video
python3 cli.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Transcribe + summarize
python3 cli.py "https://youtu.be/dQw4w9WgXcQ" --summarize

# Multiple videos
python3 cli.py URL1 URL2 URL3 -s

# Read URLs from a file (one per line, # comments ignored)
python3 cli.py --file urls.txt --summarize

# Pipe URLs from stdin
cat urls.txt | python3 cli.py -s

# Custom output directory
python3 cli.py URL1 -s -o ./MyTranscripts --summaries-dir ./MySummaries

# Force reprocess (ignore duplicates)
python3 cli.py URL1 --force
```

### CLI Options

| Flag | Short | Description |
|---|---|---|
| `--summarize` | `-s` | Generate AI summaries after transcription |
| `--file FILE` | `-f` | Text file with one URL per line |
| `--output DIR` | `-o` | Output directory for transcripts |
| `--summaries-dir DIR` | | Output directory for summaries |
| `--force` | | Reprocess even if already done |
| `--no-timestamps` | | Omit timestamps from transcripts |
| `--quiet` | `-q` | Suppress progress output |

### Duplicate Detection

The CLI tracks processed videos in a `.processed.json` manifest file inside the transcripts directory. On each run it checks:

- **Video already processed, files exist** — skipped
- **Transcript exists but summary deleted** — re-summarizes only
- **Transcript deleted** — re-fetches transcript and re-summarizes
- **`--force` flag** — reprocesses everything regardless

## Features

- **Transcript downloading** — Fetches captions from YouTube videos, Shorts, and playlists
- **Multi-method fallback** — youtube-transcript-api → yt-dlp subtitles → local Whisper transcription
- **AI summarization** — Summarize transcripts using Gemini, Ollama, or Claude CLI
- **Real-time progress** — Server-Sent Events stream status updates to the browser
- **Batch processing** — Process multiple videos or entire playlists with rate limiting
- **CLI mode** — Scriptable command-line interface with duplicate detection
- **Dark-themed UI** — Single-page web app, no framework dependencies

## Configuration

### Environment Variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `PORT` | `5555` | Port the app runs on |
| `GEMINI_API_KEY` | — | API key for Gemini summarization |
| `TRANSCRIPTIONS_DIR` | `./Transcriptions` | Output directory for transcripts |
| `SUMMARIES_DIR` | `./Summaries` | Output directory for summaries |

Create `.env` from the example:

```bash
cp .env.example .env
```

### Transcription Settings (`config.yaml`)

Controls how transcripts are fetched, with method chains based on video duration:

```yaml
transcription:
  short_max_minutes: 10
  mid_max_minutes: 20
  short_methods: [whisper]
  mid_methods: [ytdlp_subtitles, youtube_transcript_api, whisper]
  long_methods: [youtube_transcript_api, ytdlp_subtitles, whisper]
  yt_api_daily_limit: 10
  whisper_enabled: true
  whisper_model: "base"          # tiny | base | small | medium | large
  whisper_device: "auto"         # auto | cuda | cpu
  subtitle_langs: [en, en-US, en-GB]
```

### Summarization Settings (`config.yaml`)

```yaml
summarization:
  providers: [gemini, ollama, claude_cli]
  gemini_model: "gemini-2.0-flash"
  ollama_model: "llama3.1"
  ollama_url: "http://localhost:11434"
  prompt: "Summarize the following YouTube video transcript concisely..."
```

## Summarization Providers

Providers are tried in order. If one fails, the next is attempted.

| Provider | Setup | Notes |
|---|---|---|
| **Gemini** | Set `GEMINI_API_KEY` in `.env` | Fast, high quality |
| **Ollama** | Run [Ollama](https://ollama.com/) locally | Free, private, no API key |
| **Claude CLI** | Install [Claude CLI](https://docs.anthropic.com/en/docs/claude-cli) | Requires Claude subscription |

## Docker Details

- **Container name:** `tubedigest`
- **Port:** `5555` (configurable via `PORT` env var)
- **Healthcheck:** `GET /api/health` every 30s
- **Restart policy:** `unless-stopped`
- **Volumes:**
  - `./Transcriptions` — saved transcripts
  - `./Summaries` — saved summaries
  - `whisper-cache` — persistent Whisper model cache

### Changing the Port

Set `PORT` in `.env` before starting:

```bash
PORT=8080
```

Both Docker and local modes respect this variable.

## Project Structure

```
├── app.py                 # Flask routes and SSE streaming
├── cli.py                 # Command-line interface
├── src/
│   ├── fetcher.py         # Video metadata and transcript fetching
│   ├── playlist.py        # Playlist detection and extraction
│   ├── storage.py         # Transcript formatting and file saving
│   ├── jobs.py            # Background job manager (web only)
│   ├── manifest.py        # Duplicate detection manifest
│   ├── summarizer.py      # AI summarization provider abstraction
│   ├── summary_storage.py # Summary file management
│   ├── config.py          # YAML config loading
│   └── usage_tracker.py   # Daily API call tracking
├── templates/index.html   # Single-page UI
├── static/                # CSS and JS
├── config.yaml            # Transcription and summarization config
├── Dockerfile
├── docker-compose.yml
├── start.command          # macOS one-click launcher
└── stop.command           # macOS one-click shutdown
```
