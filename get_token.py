"""
Помощник получения токена ЮMoney.

Как пользоваться:
1. Двойной клик по get_token.bat
2. Укажи client_id и redirect_uri своего приложения
3. Открой ссылку, войди в ЮMoney, подтверди доступ
4. Скопируй из адресной строки ВСЮ ссылку (с code=...) и вставь в окно
5. Токен автоматически запишется в файл .env

При создании приложения (https://yoomoney.ru/myservices/new):
- Адрес сайта:  https://example.com
- Redirect URI: https://example.com/
- Notification URI: оставить пустым
- Обе галочки НЕ ставить
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def fail(msg: str) -> None:
    print("ОШИБКА:", msg)
    print("(окно закроется через 10 секунд)")
    import time

    time.sleep(10)
    sys.exit(1)


CLIENT_ID = input("client_id: ").strip()
if not CLIENT_ID:
    fail("Ты не вставил client_id")
REDIRECT_URI = input("Redirect URI (напр. https://example.com/): ").strip()
if not REDIRECT_URI:
    fail("Ты не вставил Redirect URI")

SCOPE = "account-info operation-history operation-details"

auth_url = (
    "https://yoomoney.ru/oauth/authorize?"
    + urllib.parse.urlencode(
        {
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
        }
    )
)

print()
print("1. Открой в браузере ссылку (если она открылась сама - ок):")
print(auth_url)
print("2. Войди в ЮMoney, нажми 'Подтвердить доступ'.")
print("3. Браузер покажет страницу Example Domain - это нормально.")
print("4. Скопируй ВСЮ ссылку из адресной строки (она заканчивается на code=...)")
print("   и вставь её сюда:")
print()

callback = input("Ссылка из адресной строки: ").strip()

match = re.search(r"[?&]code=([^&]+)", callback)
if not match:
    fail("В ссылке не найден параметр code. Скопируй ВСЮ ссылку из адресной строки, а не текст со страницы.")

code = urllib.parse.unquote(match.group(1))

data = urllib.parse.urlencode(
    {
        "code": code,
        "client_id": CLIENT_ID,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }
).encode()

req = urllib.request.Request(
    "https://yoomoney.ru/oauth/token",
    data=data,
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode())
except Exception as e:
    fail(f"Сбой при обмене кода: {e}. Попробуй запустить get_token.bat ещё раз.")

if "access_token" not in body:
    fail(f"ЮMoney вернул ошибку: {body}")

token = body["access_token"]

# Автовставка токена в .env
saved = False
try:
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        found = False
        for i, line in enumerate(lines):
            if line.strip().startswith("YOOMONEY_TOKEN="):
                lines[i] = f"YOOMONEY_TOKEN={token}\n"
                found = True
                break
        if not found:
            lines.append(f"YOOMONEY_TOKEN={token}\n")
        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.writelines(lines)
        saved = True
except Exception as e:
    print(f"Не удалось изменить .env автоматически: {e}")

print()
print("============================================================")
print("✅ ТОКЕН ПОЛУЧЕН:")
print(token)
print("============================================================")
if saved:
    print("Он уже сохранён в файл .env (YOOMONEY_TOKEN).")
else:
    print("Вставь его сам в файл .env в строку YOOMONEY_TOKEN=")
print("Осталось: вписать номеер кошелька (YOOMONEY_WALLET) в .env")
print("Окно закроется через 10 секунд...")
import time

time.sleep(10)