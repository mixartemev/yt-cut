# yt-cut

YouTube Clip Retranslator — Telegram-бот + HLS-сервер для нарезки отрывков из YouTube.

## Запуск
```bash
docker build -t yt-cut .
docker run --env-file .env -p 8080:8080 yt-cut
```

## .env
```
BOT_TOKEN=<токен от @BotFather>
SERVICE_URL=https://<публичный хост>
PORT=8080
```
