#!/usr/bin/env bash
# Мониторинг Stella: проверяет веб-панель и бота, шлёт алерт если что-то упало.
# Использование: crontab -e → */5 * * * * /root/stella-prod/scripts/watchdog.sh
#
# Читает BOT_TOKEN и SUPERADMIN_IDS из .env рядом со скриптом (или из ../  ).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Загрузка .env
ENV_FILE="$PROJECT_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    exit 0  # нет .env — молча выходим
fi

BOT_TOKEN=$(grep -E '^BOT_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
ADMIN_IDS=$(grep -E '^(SUPERADMIN_IDS|ALLOWED_TG_IDS)=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'" | tr ';' ',')

if [ -z "$BOT_TOKEN" ] || [ -z "$ADMIN_IDS" ]; then
    exit 0
fi

send_alert() {
    local text="$1"
    IFS=',' read -ra IDS <<< "$ADMIN_IDS"
    for uid in "${IDS[@]}"; do
        uid=$(echo "$uid" | tr -d ' ')
        [ -z "$uid" ] && continue
        curl -sf -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
            -H "Content-Type: application/json" \
            -d "{\"chat_id\": ${uid}, \"text\": \"${text}\", \"parse_mode\": \"HTML\"}" \
            > /dev/null 2>&1 || true
    done
}

PROBLEMS=""

# Проверка веб-панели
if ! curl -sf -o /dev/null --max-time 5 http://localhost:8000/health; then
    PROBLEMS="$PROBLEMS\n- Веб-панель не отвечает (localhost:8000)"
fi

# Проверка бота через systemd
if ! systemctl is-active --quiet stella-bot 2>/dev/null; then
    PROBLEMS="$PROBLEMS\n- stella-bot не активен"
fi

# Проверка веб-сервиса через systemd
if ! systemctl is-active --quiet stella-web 2>/dev/null; then
    PROBLEMS="$PROBLEMS\n- stella-web не активен"
fi

# Отправка если есть проблемы
if [ -n "$PROBLEMS" ]; then
    send_alert "<b>[WATCHDOG]</b> Проблемы:$(echo -e "$PROBLEMS")"
fi
