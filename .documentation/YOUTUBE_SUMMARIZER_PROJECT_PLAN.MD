# YouTube Transcript & Summary App — Project Plan

> **Status:** Planning
> **Last updated:** 2026-03-02

---

## App Name

The app combines transcription + AI summarization. Suggested names — pick one or propose your own:

| Name | Rationale |
|------|-----------|
| **TubeDigest** | YouTube content → digestible notes |
| **VidNotes** | Simple: video → notes |
| **ReelScribe** | Reel (video) + Scribe (write) |
| **ClipDigest** | Short clips → digest |

---

## Purpose

A cross-platform desktop (and eventually mobile) app that:
1. Accepts one or more YouTube video URLs **or a playlist URL**
2. Fetches the transcript via YouTube's built-in captions
3. Optionally generates an AI summary (overview, key points, chapters, action items)
4. Saves transcripts as `.txt` and summaries as `.md` files to a local folder

---

## Input Methods (by phase)

| Method | Phase |
|--------|-------|
| Paste single URL into app | Phase 1 |
| Paste a list of URLs (batch) | Phase 1 |
| Paste a playlist URL (bulk mode) | Phase 1 |
| macOS Share extension (Safari / Chrome) | Phase 1 |
| iOS YouTube app Share button | Phase 3 |
| Android YouTube app Share | Phase 4 |
| Linux / Windows Share integration | Phase 4 |

---

## Output Format

### Per-video transcript
- **File type:** Plain text (`.txt`)
- **Naming:** `Video_Title_YYYY-MM-DD.txt`
- **Save location:** `Transcriptions/` (or `Transcriptions/Playlist_Name/` for playlists)
- **Contents:**
  ```
  Title:    <video title>
  Video ID: <id>
  URL:      https://www.youtube.com/watch?v=<id>
  Date:     YYYY-MM-DD
  ────────────────────────────────────────────
  [00:00] ...
  [00:15] ...
  ```

### Per-video summary
- **File type:** Markdown (`.md`)
- **Naming:** `Video_Title_YYYY-MM-DD_summary.md`
- **Contents:**
  ```markdown
  # Video Title

  **URL:** https://www.youtube.com/watch?v=<id>
  **Date:** YYYY-MM-DD

  ## Overview
  2–3 sentence summary.

  ## Key Points
  - ...

  ## Chapters
  - **00:00** Introduction — ...
  - **05:30** Topic 2 — ...

  ## Action Items
  - [ ] ...
  ```

### Playlist bulk output
- A subfolder is created per playlist: `Transcriptions/Playlist_Name_YYYY-MM-DD/`
- Each video in the playlist gets its own `.txt` transcript and `.md` summary inside that folder
- A `_playlist_overview.md` is generated in the folder summarizing all videos:
  ```markdown
  # Playlist Name — Overview

  **Total videos:** N
  **Date processed:** YYYY-MM-DD

  ## Videos
  1. [Video Title](url) — one-line summary
  2. ...
  ```

---

## Phases

### Phase 1 — MVP (macOS Desktop)

**Goal:** Working app on macOS with transcript fetching and playlist support.

- [ ] Python app with simple GUI window
- [ ] Paste single URL → fetch + save transcript
- [ ] Paste multiple URLs → batch fetch + save
- [ ] **Paste playlist URL → detect playlist, fetch all videos, save each transcript**
- [ ] Timestamps toggle (include or exclude)
- [ ] macOS Share extension (Automator Service) to send URLs from Safari/Chrome
- [ ] "Open Folder" button to reveal Transcriptions folder in Finder
- [ ] Progress log in the UI (especially important for playlists)
- [ ] Error handling: clear message when no captions available

**Tech:**
- Python 3.11+
- `youtube-transcript-api` — transcript fetching
- `yt-dlp` — extract video list from a playlist URL (no download, metadata only)
- `requests` — fetch video titles
- `tkinter` — GUI (built into macOS Python)

---

### Phase 2 — AI Summarization

**Goal:** Add AI-powered summaries saved alongside transcripts.

- [ ] Pluggable AI backend system (swap providers without rewriting logic)
- [ ] **Gemini API** integration (first provider)
- [ ] **Ollama** integration (local model, fully offline)
- [ ] Summary format for each video:
  - Short overview (2–3 sentences)
  - Key points (bullet list)
  - Chapters / sections (based on content flow)
  - Action items (tasks or recommendations mentioned)
- [ ] **Playlist overview `.md`** — combined summary of all videos in a playlist
- [ ] UI toggles: "Include summary", AI provider selector
- [ ] API key storage (macOS Keychain or local `.env` file)

**Future providers (designed for but built later):**
- OpenAI / ChatGPT
- Claude (Anthropic)

**Tech additions:**
- `google-generativeai` — Gemini SDK
- `ollama` Python client
- Future: `anthropic`, `openai` SDKs

---

### Phase 3 — Cross-platform Desktop + iOS

**Goal:** Expand to other desktop OS and iOS.

- [ ] Test and fix for **Windows**
- [ ] Test and fix for **Linux**
- [ ] Package as installers (`.exe`, `.deb`/`.AppImage`, `.app`)
- [ ] **iOS Share extension** — share from YouTube app → app receives URL
  - Likely requires a companion iOS app (Swift / React Native / Flutter)

---

### Phase 4 — Android + Full Mobile

**Goal:** Android support and polished mobile experience.

- [ ] Android Share intent receiver
- [ ] Decide mobile stack: React Native or Flutter (write once, run on iOS + Android)
- [ ] Sync transcriptions folder to iCloud / Google Drive (optional)

---

## Rate Limiting

To avoid getting blocked by YouTube when processing batches or playlists, the app will implement the following strategy:

### Delays between requests
| Scenario | Delay |
|----------|-------|
| Single video fetch | No delay |
| Batch (multiple URLs) | 2–5 seconds between each video |
| Playlist | 2–5 seconds between each video |
| After every 10 videos in a batch/playlist | Extra 15-second pause |

### Behavior
- Delays are randomized within the range (e.g. 2–5s) to appear more human-like
- The UI log will show when the app is waiting: `Waiting 3s before next request...`
- User can configure the delay range in settings (Phase 2)
- If YouTube returns an error suggesting rate limiting, the app will automatically back off and retry once after 30 seconds before marking the video as failed

### AI API rate limiting (Phase 2)
- Gemini and Ollama requests are also delayed between calls
- Gemini free tier: 15 requests per minute — app will respect this automatically
- Ollama (local): no rate limit, but will throttle if system is under load

---

## ⚠️ Known Limitations & Future Work

| Limitation | Notes |
|------------|-------|
| **No captions = no transcript** | If a video has CC disabled or no auto-captions, `youtube-transcript-api` will fail. Future fix: download audio + run **OpenAI Whisper** (local speech-to-text) as fallback. Phase 2/3 item. |
| **Auto-generated caption quality** | YouTube's auto-captions can have errors, especially for accents or technical terms. Whisper fallback would improve accuracy. |
| **Large playlists** | A 100+ video playlist can take significant time. Progress bar and the ability to pause/resume batch jobs should be considered. |
| **YouTube ToS** | Fetching transcripts is low-risk (same data shown in the player), but worth monitoring if YouTube changes caption endpoints. |
| **Rate limiting** | Handled via built-in delays (see Rate Limiting section above). |

---

## Project File Structure

```
Auto YT transcribe/
├── YOUTUBE_SUMMARIZER_PROJECT_PLAN.MD  ← this file
├── README.md                ← setup & usage instructions (Phase 1)
├── requirements.txt         ← Python dependencies
├── .env.example             ← API key template (never commit .env)
├── transcriber.py           ← main entry point (GUI + CLI modes)
├── src/
│   ├── fetcher.py           ← YouTube transcript + title fetching
│   ├── playlist.py          ← playlist URL detection + video list extraction
│   ├── summarizer.py        ← AI summarization (pluggable backends)
│   ├── storage.py           ← file naming, folder structure, saving
│   └── gui.py               ← GUI window code
└── Transcriptions/          ← output folder (already exists)
    ├── Video_Title_2026-03-02.txt
    ├── Video_Title_2026-03-02_summary.md
    └── Playlist_Name_2026-03-02/
        ├── _playlist_overview.md
        ├── Video_1_Title.txt
        ├── Video_1_Title_summary.md
        └── ...
```

---

## Tech Stack Summary

| Layer | Tool | Notes |
|-------|------|-------|
| Language | Python 3.11+ | Cross-platform, large ecosystem |
| GUI | tkinter | Built into Python; works on Mac/Win/Linux |
| Transcripts | `youtube-transcript-api` | Same data as youtubetranscript.com etc. |
| Playlist parsing | `yt-dlp` | Extract video URLs from playlist without downloading |
| HTTP | `requests` | Fetch video titles |
| AI — Gemini | `google-generativeai` | Phase 2 |
| AI — Local | `ollama` | Phase 2, offline |
| AI — Claude | `anthropic` | Phase 2+ future |
| AI — OpenAI | `openai` | Phase 2+ future |
| Packaging | PyInstaller | Bundle into `.app` / `.exe` |
| macOS Share | Automator Service | Phase 1 |
| iOS Share | Swift App Extension | Phase 3 |

---

## Open Questions

- [ ] **App name** — pick from suggestions or propose one
- [ ] **Gemini API key** — will need one before Phase 2 (free tier available)
- [ ] **Ollama model** — which local model for summarization? (e.g. `llama3`, `mistral`)
- [ ] **iCloud sync** — should the Transcriptions folder live in iCloud Drive?
- [ ] **Playlist size limit** — should there be a max video count per batch, or just let it run?
