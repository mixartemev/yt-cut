"""
YouTube Clip Retranslator — Telegram bot + aiohttp clip server.

Env vars:
    BOT_TOKEN    — Telegram bot token from @BotFather
    SERVICE_URL  — public base URL for clip links (e.g. https://example.com)
    PORT         — HTTP server port (default 8080)
"""

import os
import re
import asyncio
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


BOT_TOKEN = os.environ["BOT_TOKEN"]
SERVICE_URL = os.environ.get("SERVICE_URL", "http://localhost:8080")
PORT = int(os.environ.get("PORT", "8080"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ── Clip server ──────────────────────────────────────────────────────────────


def parse_youtube_url(url: str) -> str:
    """Extract video ID and return canonical URL."""
    m = re.search(
        r"(?:youtu\.be/|youtube\.com/watch\?v=|youtube\.com/embed/)([a-zA-Z0-9_-]{11})",
        url,
    )
    if not m:
        raise ValueError(f"Invalid YouTube URL: {url}")
    return f"https://www.youtube.com/watch?v={m.group(1)}"


async def handle_clip(request: web.Request) -> web.StreamResponse:
    url = request.query.get("url")
    start = request.query.get("start")
    end = request.query.get("end")

    if not url or start is None or end is None:
        return web.json_response({"error": "Required params: url, start, end"}, status=400)

    try:
        start_f, end_f = float(start), float(end)
    except ValueError:
        return web.json_response({"error": "start and end must be numbers"}, status=400)

    if end_f <= start_f:
        return web.json_response({"error": "end must be greater than start"}, status=400)

    try:
        canonical = parse_youtube_url(url)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)

    # Resolve direct stream URL via yt-dlp
    proc = await asyncio.create_subprocess_exec(
        "yt-dlp",
        "-f", "best[ext=mp4]/best", "-g", canonical,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

    if proc.returncode != 0:
        return web.json_response(
            {"error": f"yt-dlp error: {stderr.decode().strip()}"}, status=502,
        )

    stream_url = stdout.decode().strip().splitlines()[0]
    duration = end_f - start_f

    # Stream clip via ffmpeg
    ffmpeg = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-ss", str(start_f),
        "-i", stream_url,
        "-t", str(duration),
        "-c", "copy",
        "-movflags", "frag_keyframe+empty_moov",
        "-f", "mp4",
        "-loglevel", "error",
        "pipe:1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "video/mp4",
            "Content-Disposition": "inline; filename=clip.mp4",
        },
    )
    await resp.prepare(request)

    try:
        while True:
            chunk = await ffmpeg.stdout.read(64 * 1024)
            if not chunk:
                break
            await resp.write(chunk)
    finally:
        ffmpeg.terminate()
        await ffmpeg.wait()

    return resp


# ── Telegram bot ─────────────────────────────────────────────────────────────

class ClipForm(StatesGroup):
    start = State()
    end = State()


def parse_time(text: str) -> float:
    """Parse 'мин:сек' (e.g. 8:54) to seconds."""
    m = re.fullmatch(r"(\d+):(\d{1,2})", text.strip())
    if not m:
        raise ValueError
    minutes, seconds = int(m.group(1)), int(m.group(2))
    if seconds >= 60:
        raise ValueError
    return minutes * 60 + seconds


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет! Отправь ссылку на YouTube ролик, чтобы создать отрывок.",
        reply_markup=ReplyKeyboardRemove(),
    )


@dp.message(~F.text)
async def ignore_non_text(message: Message):
    pass


@dp.message(ClipForm.start)
async def process_start(message: Message, state: FSMContext):
    try:
        start = parse_time(message.text)
    except ValueError:
        await message.answer("Некорректный формат. Введите время как мин:сек (например 8:54):")
        return
    await state.update_data(start=start)
    await state.set_state(ClipForm.end)
    await message.answer("Введите время конца в формате мин:сек (например 10:30):")


@dp.message(ClipForm.end)
async def process_end(message: Message, state: FSMContext):
    try:
        end = parse_time(message.text)
    except ValueError:
        await message.answer("Некорректный формат. Введите время как мин:сек (например 10:30):")
        return

    data = await state.get_data()
    start = data["start"]

    if end <= start:
        await message.answer("Время конца должно быть больше времени начала. Попробуйте ещё раз:")
        return

    await state.clear()

    clip_url = f"{SERVICE_URL}/clip?url={quote(data['url'])}&start={start}&end={end}"
    share_url = f"https://t.me/share/url?url={quote(clip_url)}"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Поделиться с контактом", url=share_url)],
        ]
    )
    await message.answer("Отрывок готов! Нажмите кнопку, чтобы поделиться:", reply_markup=kb)


@dp.message()
async def process_url(message: Message, state: FSMContext):
    url = message.text.strip()
    if not re.search(
        r"(?:youtu\.be/|youtube\.com/watch\?v=|youtube\.com/embed/)[a-zA-Z0-9_-]{11}",
        url,
    ):
        await message.answer("Отправьте ссылку на YouTube ролик:")
        return
    await state.update_data(url=url)
    await state.set_state(ClipForm.start)
    await message.answer("Введите время начала в формате мин:сек (например 8:54):")


# ── Entrypoint ───────────────────────────────────────────────────────────────


async def main():
    app = web.Application()
    app.router.add_get("/clip", handle_clip)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
