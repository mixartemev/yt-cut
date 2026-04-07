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
import time
import tempfile
import shutil
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

VIDEO_ID_RE = re.compile(r"(?:youtu\.be/|youtube\.com/watch\?v=|youtube\.com/embed/)([a-zA-Z0-9_-]{11})")

_CACHE_TTL = 1800
_url_cache: dict[str, tuple[str, float]] = {}
_hls_cache: dict[tuple, tuple[str, float]] = {}
_title_cache: dict[tuple, str] = {}


# ── Clip server ──────────────────────────────────────────────────────────────


async def _resolve(video_id: str) -> str:
    now = time.time()
    cached = _url_cache.get(video_id)
    if cached and now - cached[1] < _CACHE_TTL:
        return cached[0]

    proc = await asyncio.create_subprocess_exec(
        "yt-dlp", "-f", "best[ext=mp4]/best", "-g",
        f"https://www.youtube.com/watch?v={video_id}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode().strip())

    url = stdout.decode().strip().splitlines()[0]
    _url_cache[video_id] = (url, now)
    return url


def _cleanup_hls():
    now = time.time()
    for key in [k for k, (_, ts) in _hls_cache.items() if now - ts > _CACHE_TTL]:
        tmpdir, _ = _hls_cache.pop(key)
        shutil.rmtree(tmpdir, ignore_errors=True)


async def _generate_hls(video_id: str, start: float, end: float) -> str:
    """end=0 means no right trim."""
    key = (video_id, start, end)
    _cleanup_hls()

    cached = _hls_cache.get(key)
    if cached:
        return cached[0]

    stream_url = await _resolve(video_id)
    tmpdir = tempfile.mkdtemp(prefix="hls_")

    cmd = [
        "ffmpeg",
        "-ss", str(start),
        "-i", stream_url,
    ]
    if end:
        cmd += ["-t", str(end - start)]
    cmd += [
        "-c", "copy",
        "-f", "hls",
        "-hls_time", "4",
        "-hls_playlist_type", "vod",
        "-hls_segment_filename", os.path.join(tmpdir, "seg%d.ts"),
        "-loglevel", "error",
        os.path.join(tmpdir, "stream.m3u8"),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

    if proc.returncode != 0:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise RuntimeError(stderr.decode().strip())

    _hls_cache[key] = (tmpdir, time.time())
    return tmpdir


async def handle_stream(request: web.Request) -> web.Response:
    v = request.match_info["v"]
    start_f = float(request.match_info["start"])
    end_f = float(request.match_info.get("end", 0))

    if end_f and end_f <= start_f:
        return web.json_response({"error": "end must be greater than start"}, status=400)

    # Telegram link preview bot — return HTML with OG tags
    ua = request.headers.get("User-Agent", "")
    if "TelegramBot" in ua:
        thumb = f"https://img.youtube.com/vi/{v}/hqdefault.jpg"
        title = _title_cache.get((v, start_f, end_f), "YouTube Clip")
        html = (
            f'<meta property="og:type" content="video.other">'
            f'<meta property="og:image" content="{thumb}">'
            f'<meta property="og:title" content="{title}">'
        )
        return web.Response(text=html, content_type="text/html")

    try:
        tmpdir = await _generate_hls(v, start_f, end_f)
    except RuntimeError as e:
        return web.json_response({"error": str(e)}, status=502)

    with open(os.path.join(tmpdir, "stream.m3u8")) as f:
        m3u8 = f.read()

    # Rewrite local filenames to absolute URLs
    ts_base = f"{SERVICE_URL}/ts/{v}/{start_f}/{end_f}" if end_f else f"{SERVICE_URL}/ts/{v}/{start_f}"
    m3u8 = re.sub(
        r"seg(\d+)\.ts",
        lambda m: f"{ts_base}?seg={m.group(1)}",
        m3u8,
    )

    return web.Response(text=m3u8, content_type="application/vnd.apple.mpegurl")


async def handle_ts(request: web.Request) -> web.Response:
    v = request.match_info["v"]
    start_f = float(request.match_info["start"])
    end_f = float(request.match_info.get("end", 0))
    seg = request.query.get("seg")

    if seg is None:
        return web.json_response({"error": "Required param: seg"}, status=400)

    key = (v, start_f, end_f)
    cached = _hls_cache.get(key)
    if not cached:
        return web.json_response({"error": "Session expired, reload playlist"}, status=404)

    ts_path = os.path.join(cached[0], f"seg{seg}.ts")
    if not os.path.isfile(ts_path):
        return web.json_response({"error": "Segment not found"}, status=404)

    return web.FileResponse(ts_path, headers={"Content-Type": "video/mp2t"})


# ── Telegram bot ─────────────────────────────────────────────────────────────

class ClipForm(StatesGroup):
    start = State()
    end = State()
    title = State()


def parse_time(text: str) -> float:
    """Parse 'мин:сек' (e.g. 8:54) or '0' to seconds."""
    text = text.strip()
    if text == "0":
        return 0
    m = re.fullmatch(r"(\d+):(\d{1,2})", text)
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
        await message.answer("Некорректный формат. Введите время как мин:сек (например 10:30 или 0:00):")
        return

    data = await state.get_data()
    start = data["start"]

    if end and end <= start:
        await message.answer("Время конца должно быть больше времени начала. Попробуйте ещё раз:")
        return

    await state.update_data(end=end)
    await state.set_state(ClipForm.title)
    await message.answer("Введите название ролика:")


@dp.message(ClipForm.title)
async def process_title(message: Message, state: FSMContext):
    title = message.text.strip()
    data = await state.get_data()
    await state.clear()

    start, end, v = data["start"], data["end"], data["v"]
    _title_cache[(v, float(start), float(end))] = title
    clip_url = f"{SERVICE_URL}/{v}/{start}/{end}" if end else f"{SERVICE_URL}/{v}/{start}"
    share_url = f"https://t.me/share/url?url={quote(clip_url)}"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Поделиться с контактом", url=share_url)],
        ]
    )
    await message.answer("Отрывок готов! Нажмите кнопку, чтобы поделиться:", reply_markup=kb)


@dp.message()
async def process_url(message: Message, state: FSMContext):
    m = VIDEO_ID_RE.search(message.text.strip())
    if not m:
        await message.answer("Отправьте ссылку на YouTube ролик:")
        return
    await state.update_data(v=m.group(1))
    await state.set_state(ClipForm.start)
    await message.answer("Введите время начала в формате мин:сек (например 8:54):")


# ── Entrypoint ───────────────────────────────────────────────────────────────


async def main():
    app = web.Application()
    vid = r"{v:[a-zA-Z0-9_-]{11}}"
    app.router.add_get(f"/{vid}/{{start}}", handle_stream)
    app.router.add_get(f"/{vid}/{{start}}/{{end}}", handle_stream)
    app.router.add_get(f"/ts/{vid}/{{start}}", handle_ts)
    app.router.add_get(f"/ts/{vid}/{{start}}/{{end}}", handle_ts)

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
