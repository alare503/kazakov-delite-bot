import asyncio
import json
import logging
import urllib.parse

import aiohttp

logger = logging.getLogger(__name__)

QUICKPAY_URL = "https://yoomoney.ru/quickpay/confirm.xml"
API_HISTORY_URL = "https://yoomoney.ru/api/operation-history"


def build_payment_url(wallet: str, amount: int, label: str, bot_username: str = "") -> str:
    """Ссылка на платёжную форму ЮMoney (оплата картой)."""
    params = {
        "quickpay-form": "shop",
        "receiver": wallet,
        "sum": str(amount),
        "label": label,
        "paymentType": "AC",  # оплата с банковской карты
        "targets": "Подписка Anti-Delete Bot",
        "successURL": f"https://t.me/{bot_username}" if bot_username else "",
    }
    return f"{QUICKPAY_URL}?{urllib.parse.urlencode(params)}"


def _auth_header(token: str) -> str:
    return f"Bearer {token}"


async def check_payment(token: str, label: str, amount: int) -> bool:
    """
    Проверяет через API ЮMoney, пришёл ли платёж с нужным label.
    Провайдер может резать TLS к yoomoney.ru — делаем несколько коротких
    попыток с новыми соединениями (принудительно Connection: close).
    """
    data = {"type": "deposition", "label": label, "records": 10}
    headers = {
        "Authorization": _auth_header(token),
        "Content-Type": "application/x-www-form-urlencoded",
        "Connection": "close",
    }
    timeout = aiohttp.ClientTimeout(total=12)

    for attempt in range(8):
        body = None
        status = None
        try:
            async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(force_close=True)) as session:
                async with session.post(API_HISTORY_URL, data=data, headers=headers, timeout=timeout) as resp:
                    status = resp.status
                    body = await resp.text()
        except Exception as e:
            logger.warning(f"ЮMoney попытка {attempt + 1}: {type(e).__name__}: {e}")
            await asyncio.sleep(2)
            continue

        if status >= 500:
            logger.warning(f"ЮMoney HTTP {status} (попытка {attempt + 1}): {body[:150]}")
            await asyncio.sleep(2)
            continue
        if status != 200:
            logger.warning(f"ЮMoney HTTP {status}: {body[:200]}")
            return False
        break
    else:
        return False

    try:
        data_json = json.loads(body)
    except json.JSONDecodeError:
        logger.warning(f"Не удалось разобрать ответ ЮMoney: {body[:200]}")
        return False

    if "error" in data_json:
        logger.warning(f"ЮMoney вернул ошибку: {data_json['error']}")
        return False

    for op in data_json.get("operations", []):
        if op.get("label") == label and op.get("status") == "success":
            try:
                sum_val = float(op.get("amount", 0))
            except (TypeError, ValueError):
                sum_val = 0.0
            if sum_val >= amount:
                logger.info(f"Оплата подтверждена: label={label}, сумма={sum_val}")
                return True

    return False