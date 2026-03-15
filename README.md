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

If files are moved to different subfolders, the manifest self-heals by searching recursively for the file by name and updating the stored path automatically.

## Features

- **Transcript downloading** — Fetches captions from YouTube videos, Shorts, and playlists
- **Multi-method fallback** — youtube-transcript-api → pytubefix/yt-dlp subtitles → local Whisper transcription
- **Switchable video backend** — pytubefix (default) or yt-dlp for metadata, subtitles, audio, and playlists — configurable with automatic fallback
- **AI summarization** — Summarize transcripts using Claude CLI, Claude Proxy, Gemini, or Ollama
- **Real-time progress** — Server-Sent Events stream status updates to the browser
- **Batch processing** — Process multiple videos or entire playlists with rate limiting
- **CLI mode** — Scriptable command-line interface with duplicate detection
- **Dark-themed UI** — Single-page web app with filterable transcript list, no framework dependencies

## Configuration

### Environment Variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `PORT` | `5555` | Port the app runs on |
| `GEMINI_API_KEY` | — | API key for Gemini summarization |
| `CLAUDE_PROXY_URL` | `http://host.docker.internal:9100` | URL of the Claude proxy (for Docker) |
| `OLLAMA_URL` | `http://localhost:11434` | URL of the Ollama server |
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
  # Video backend for metadata, subtitles, audio, and playlists (tried in order)
  video_backend: [pytubefix, ytdlp]

  short_max_minutes: 10
  mid_max_minutes: 20
  short_methods: [whisper]
  mid_methods: [pytubefix_subtitles, youtube_transcript_api, whisper]
  long_methods: [youtube_transcript_api, pytubefix_subtitles, whisper]
  yt_api_daily_limit: 10
  whisper_enabled: true
  whisper_model: "base"          # tiny | base | small | medium | large
  whisper_device: "auto"         # auto | cuda | cpu
  subtitle_langs: [en, en-US, en-GB]
```

To switch to yt-dlp as the primary backend, change the order:

```yaml
video_backend: [ytdlp, pytubefix]
```

### Summarization Settings (`config.yaml`)

```yaml
summarization:
  providers: [claude_cli, claude_proxy, gemini, ollama]
  gemini_model: "gemini-2.0-flash"
  ollama_model: "llama3.1"
  ollama_url: "http://localhost:11434"
  claude_proxy_url: "http://host.docker.internal:9100"
  prompt: "Summarize the following YouTube video transcript concisely..."
```

## Summarization Providers

Providers are tried in order. If one fails, the next is attempted.

| Provider | Setup | Notes |
|---|---|---|
| **Claude CLI** | Install [Claude Code](https://docs.anthropic.com/en/docs/claude-code/getting-started) | Requires Claude subscription, local only |
| **Claude Proxy** | Run `python claude_proxy.py` on the host | For Docker — proxies to Claude CLI on the host |
| **Gemini** | Set `GEMINI_API_KEY` in `.env` | Fast, high quality |
| **Ollama** | Run [Ollama](https://ollama.com/) locally | Free, private, no API key |

### Claude Proxy (Docker)

When running in Docker, the container can't access the host's Claude CLI directly. The Claude Proxy bridges this gap — run it on the host and the container sends summarization requests to it over HTTP.

```bash
# On the host machine (outside Docker)
python claude_proxy.py              # listens on 0.0.0.0:9100
python claude_proxy.py --port 9200  # custom port
```

The container reaches it via `http://host.docker.internal:9100` by default. Override with `CLAUDE_PROXY_URL` in `.env` or `claude_proxy_url` in `config.yaml`.

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
├── claude_proxy.py        # HTTP proxy for Docker → host Claude CLI access
├── src/
│   ├── pipeline.py        # Shared processing pipeline (CLI + web)
│   ├── fetcher.py         # Video metadata and transcript fetching
│   ├── playlist.py        # Playlist detection and extraction
│   ├── storage.py         # Transcript formatting, file saving, directory constants
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
