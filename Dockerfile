FROM node:20-alpine AS miniapp
WORKDIR /miniapp
COPY miniapp/package.json miniapp/package-lock.json* ./
RUN npm install
COPY miniapp/ ./
RUN npm run build

FROM python:3.14-slim
RUN apt update; apt install -y --no-install-recommends ffmpeg; rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .
#COPY bot.py .
COPY --from=miniapp /miniapp/dist ./miniapp/dist

CMD ["python", "bot.py"]
