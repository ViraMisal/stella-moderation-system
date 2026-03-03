# Развёртывание без Docker (systemd + nginx)

## 1. Создать пользователя и директорию

```bash
useradd -r -s /bin/false -d /opt/stella stella
mkdir -p /opt/stella/data /opt/stella/logs
cp -r /path/to/repo/* /opt/stella/
chown -R stella:stella /opt/stella
```

## 2. Виртуальное окружение

```bash
cd /opt/stella
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 3. Переменные окружения

```bash
cp .env.example .env
nano .env   # заполнить BOT_TOKEN, SECRET_KEY и DATABASE_URL
```

## 4. Первый запуск БД

```bash
.venv/bin/python run.py migrate
```

## 5. Systemd-сервисы

```bash
cp deploy/systemd/stella-bot.service /etc/systemd/system/
cp deploy/systemd/stella-web.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now stella-bot stella-web
```

## 6. Nginx

```bash
cp deploy/nginx/stella.conf /etc/nginx/sites-available/stella
# Отредактировать your-domain.com в файле
ln -s /etc/nginx/sites-available/stella /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

## 7. TLS (Let's Encrypt)

```bash
apt install certbot python3-certbot-nginx
certbot --nginx -d your-domain.com
```

## Просмотр логов

```bash
journalctl -u stella-bot -f
journalctl -u stella-web -f
```
