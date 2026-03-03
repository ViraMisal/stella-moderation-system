FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata curl \
    && rm -rf /var/lib/apt/lists/*

# Непривилегированный пользователь
RUN useradd -r -s /bin/false -u 1000 stella

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data /logs && chown -R stella:stella /data /logs /app

ENV DATA_DIR=/data \
    LOG_DIR=/logs \
    ENV=production \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Moscow

USER stella

EXPOSE 8000

CMD ["python", "run.py", "all"]
