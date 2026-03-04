# TubeDigest

A local web app that downloads YouTube transcripts and summarizes them with AI. Supports individual videos, Shorts, and full playlists.

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

## Features

- **Transcript downloading** — Fetches captions from YouTube videos, Shorts, and playlists
- **Multi-method fallback** — youtube-transcript-api → yt-dlp subtitles → local Whisper transcription
- **AI summarization** — Summarize transcripts using Gemini, Ollama, or Claude CLI
- **Real-time progress** — Server-Sent Events stream status updates to the browser
- **Batch processing** — Process multiple videos or entire playlists with rate limiting
- **Dark-themed UI** — Single-page app, no framework dependencies

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
├── src/
│   ├── fetcher.py         # Video metadata and transcript fetching
│   ├── playlist.py        # Playlist detection and extraction
│   ├── storage.py         # Transcript formatting and file saving
│   ├── jobs.py            # Background job manager
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
