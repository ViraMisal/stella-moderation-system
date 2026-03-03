FROM python:3.11-slim

WORKDIR /app

# Системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Зависимости Python (отдельным слоем — кэшируются при изменении кода)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Исходники
COPY . .

# Данные и логи вынесены в volumes (не в образ)
RUN mkdir -p /data /logs

ENV DATA_DIR=/data \
    LOG_DIR=/logs \
    ENV=production \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Moscow

EXPOSE 8000

# CMD переопределяется в docker-compose.yml
CMD ["python", "run.py", "all"]
