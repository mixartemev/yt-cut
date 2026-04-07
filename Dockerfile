FROM python:3.14-slim
RUN apt update; apt install -y --no-install-recommends ffmpeg; rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .
#COPY bot.py .

CMD ["python", "bot.py"]
