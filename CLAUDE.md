# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

YouTube Clip Retranslator — a single-process service combining an aiohttp clip server and a Telegram bot (aiogram). Extracts clips from YouTube videos via yt-dlp + ffmpeg and lets users share streaming links through Telegram.

## Running

```bash
source venv/bin/activate
BOT_TOKEN=<token_from_botfather> SERVICE_URL=https://<public_host> python bot.py
# optional: PORT=9000 (default 8080)
```

## Dependencies

- **Python 3.14** with venv at `./venv`
- **pip packages:** aiogram (includes aiohttp)
- **System tools (must be on PATH):** `yt-dlp`, `ffmpeg`

Install pip deps: `pip install aiogram`

## API

- `GET /clip?url=<youtube_url>&start=<seconds>&end=<seconds>` — streams an MP4 clip

## Telegram Bot

aiogram 3.x bot with FSM-based conversation flow:
1. User presses "Поделиться отрывком" (reply keyboard button)
2. Bot asks for YouTube URL, start time (мин:сек), end time (мин:сек)
3. Bot generates a clip URL and shows an inline button that opens Telegram's native share dialog (`https://t.me/share/url?url=...`)

Env vars:
- `BOT_TOKEN` — from @BotFather (required)
- `SERVICE_URL` — public base URL for clip links (default: `http://localhost:8080`)
- `PORT` — HTTP server port (default: `8080`)

## Architecture

Single file `bot.py` running two things in one asyncio loop:

**aiohttp server** (`/clip` endpoint):
- `parse_youtube_url()` — extracts video ID from various YouTube URL formats
- `handle_clip()` — async: resolves direct URL via `yt-dlp -g`, streams ffmpeg output as `StreamResponse`

**aiogram bot**:
- `ClipForm` FSM — states: url -> start -> end
- `parse_time()` — converts "мин:сек" to seconds
- Handlers collect params, build clip URL, present share button
