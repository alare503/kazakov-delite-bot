#!/usr/bin/env bash
# Запуск бота Kazakov Delite на Linux. Работает как демон с авто-перезапуском.
set -e
cd "$(dirname "$0")"

if [ ! -f ".env" ]; then
    echo "Файл .env не найден. Скопируй его на сервер."
    exit 1
fi

# Устанавливаем зависимости при первом запуске
if [ ! -d "venv" ]; then
    python3 -m venv venv
    venv/bin/pip install -U pip
    venv/bin/pip install -r requirements.txt
fi

echo "Запуск бота..."
while true; do
    venv/bin/python -u bot.py
    echo "Бот завершил работу с кодом $? — через 5 сек перезапуск..."
    sleep 5
done