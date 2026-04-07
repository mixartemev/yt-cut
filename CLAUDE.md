# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

YouTube Clip Retranslator — a single-process service combining an aiohttp HLS server and a Telegram bot (aiogram). Generates HLS streams from YouTube videos via yt-dlp + ffmpeg and lets users share streaming links through Telegram.

## Running

```bash
docker build -t yt-cut .
docker run --env-file .env -p 8080:8080 yt-cut
```

Dev (without Docker):
```bash
source venv/bin/activate
python bot.py
```

## Dependencies

- **Python 3.14**
- **pip packages:** aiogram (includes aiohttp), python-dotenv
- **System tools (must be on PATH):** `yt-dlp`, `ffmpeg`

## .env

- `BOT_TOKEN` — from @BotFather (required)
- `SERVICE_URL` — public base URL for clip links (default: `http://localhost:8080`)
- `PORT` — HTTP server port (default: `8080`)

## API

- `GET /{video_id}/{start}` — HLS playlist (M3U8), plays from `start` seconds to end of video
- `GET /{video_id}/{start}/{end}` — HLS playlist (M3U8), plays from `start` to `end` seconds
- `GET /ts/{video_id}/{start}[/{end}]?seg=N` — individual TS segment from cached HLS

When requested by TelegramBot (User-Agent), the stream endpoint returns HTML with OG meta tags (thumbnail + title) for link previews.

## Telegram Bot

aiogram 3.x bot with FSM-based conversation flow:
1. User sends a YouTube URL
2. Bot asks for start time (min:sec or 0), end time (min:sec or 0 for no trim), and clip title
3. Bot generates a clip URL with link preview and an inline share button (`https://t.me/share/url?url=...`)

## Architecture

Single file `bot.py` running two things in one asyncio loop:

**aiohttp server**:
- `_resolve()` — resolves direct stream URL via `yt-dlp -g`, cached for 30 min
- `_generate_hls()` — runs ffmpeg to generate HLS segments (4s each) in a temp dir, cached for 30 min
- `handle_stream()` — returns M3U8 playlist (or OG HTML for TelegramBot)
- `handle_ts()` — serves individual TS segment files from cache

**aiogram bot**:
- `ClipForm` FSM — states: start → end → title
- `parse_time()` — converts "min:sec" or "0" to seconds
- Handlers collect params, store title in memory, build clip URL, present share button
