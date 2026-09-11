import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject, CommandStart, ChatMemberUpdatedFilter, IS_NOT_MEMBER, IS_MEMBER, Filter
from aiogram.types import (
    BusinessConnection,
    BusinessMessagesDeleted,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ChatMemberUpdated,
)

import database as db
import yoomoney

from dotenv import load_dotenv

load_dotenv(override=True)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")
BOT_NAME = os.getenv("BOT_NAME", BOT_USERNAME or "bot")
YOOMONEY_TOKEN = os.getenv("YOOMONEY_TOKEN", "")
YOOMONEY_WALLET = os.getenv("YOOMONEY_WALLET", "")
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except (TypeError, ValueError):
    ADMIN_ID = 0

PRICE = 100
PAYMENT_WAIT_SECONDS = 7 * 24 * 60 * 60  # сколько ждём оплату после нажатия кнопки

BANNER = Path(__file__).resolve().parent / "assets" / "banner.png"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def sender_display(sender_id: int, sender_username=None, sender_name=None) -> str:
    """Форматирует отправителя: сначала @username, иначе имя, иначе ID."""
    if sender_username:
        return "@" + sender_username
    return sender_name or f"ID:{sender_id}"


class DeletionFilter(Filter):
    async def __call__(self, msg: Message) -> bool:
        date_val = msg.date
        if date_val.tzinfo is None:
            date_val = date_val.replace(tzinfo=timezone.utc)
        return (
            msg.from_user is None
            and msg.text is None
            and msg.caption is None
            and abs((date_val - EPOCH).total_seconds()) < 60
        )


# ── /start ────────────────────────────────────────────────────────────────
def _start_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛡️ Подключить личные чаты",
                    url=f"https://t.me/{BOT_NAME}?startchannel&admin=add_manage_chat",
                )
            ],
            [
                InlineKeyboardButton(text="💰 Купить подписку", callback_data="pay"),
                InlineKeyboardButton(text="🔧 Настройки", callback_data="settings"),
            ],
        ]
    )


@router.message(CommandStart())
async def cmd_start(msg: Message):
    db.add_user(msg.from_user.id, msg.from_user.username)
    user_id = msg.from_user.id

    active = db.is_active(user_id)
    if active:
        sub = db.get_subscription(user_id)
        until = sub["active_until"] if sub else "??"
        await msg.answer_photo(
            FSInputFile(BANNER),
            caption=(
                "🎉 <b>Подписка активна!</b>\n\n"
                f"⏳ Действует до: <b>{until}</b>\n\n"
                "📌 <b>Как пользоваться:</b>\n\n"
                "🔹 <b>Личные чаты:</b>\n"
                "Telegram → Профиль → «Автоматизация чатов» → "
                "добавь @" + BOT_NAME + "\n\n"
                "🔹 <b>Группы:</b> добавь бота админом\n\n"
                "Статус: /status · Настройки: /settings"
            ),
            parse_mode="HTML",
            reply_markup=_start_kb(),
        )
        return

    await msg.answer_photo(
        FSInputFile(BANNER),
        caption=(
            "👋 <b>Anti-Delete Bot</b>\n\n"
            "Я <b>спасаю удалённые и изменённые сообщения</b>\n"
            "и сохраняю <b>исчезающие фото</b> 🛡️\n\n"
            "📌 <b>Шаг 1 — личные чаты:</b>\n"
            "1. Нажми /subscribe (100 ₽/мес)\n"
            "2. Telegram → Профиль → «Автоматизация чатов»\n"
            "   → добавь @" + BOT_NAME + "\n\n"
            "📌 <b>Шаг 2 — группы:</b>\n"
            "Добавь меня в группу как <b>администратора</b>\n\n"
            "💰 Подписка: <b>100 ₽ / месяц</b>"
        ),
        parse_mode="HTML",
        reply_markup=_start_kb(),
    )


# ── /subscribe ────────────────────────────────────────────────────────────
@router.message(Command("subscribe"))
async def cmd_subscribe(msg: Message):
    db.add_user(msg.from_user.id)

    if db.is_active(msg.from_user.id):
        sub = db.get_subscription(msg.from_user.id)
        until = sub["active_until"] if sub else "??"
        await msg.answer(
            f"✅ У тебя уже есть активная подписка!\n"
            f"⏳ Действует до: <b>{until}</b>\n\n"
            f"Настройки: /settings",
            parse_mode="HTML",
        )
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"💳 Оплатить {PRICE} ₽", callback_data="pay"
                )
            ],
            [
                InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings"),
            ],
        ]
    )
    await msg.answer(
        f"💰 <b>Подписка Anti-Delete Bot</b>\n\n"
        f"Стоимость: <b>{PRICE} ₽ за 30 дней</b>\n\n"
        f"Что даёт:\n"
        f"🖼 Сохранение исчезающих фото и медиа\n"
        f"🗑 Ловля удалённых сообщений в личках и группах\n"
        f"✏️ Ловля изменённых сообщений\n\n"
        f"Оплата через ЮMoney, активация автоматическая.",
        parse_mode="HTML",
        reply_markup=kb,
    )


@router.callback_query(F.data == "pay")
async def cb_pay(call: CallbackQuery):
    db.add_user(call.from_user.id)

    if db.is_active(call.from_user.id):
        await call.answer("Подписка уже активна!")
        return

    db.mark_receipt_pending(call.from_user.id)

    pay_url = yoomoney.build_payment_url(
        wallet=YOOMONEY_WALLET,
        amount=PRICE,
        label=str(call.from_user.id),
        bot_username=BOT_USERNAME,
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 Перейти к оплате", url=pay_url
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Я оплатил — проверить", callback_data="check_pay"
                )
            ],
            [
                InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings"),
            ],
        ]
    )

    await call.answer()
    await call.message.answer(
        f"💳 <b>Оплата {PRICE} ₽</b>\n\n"
        f"Нажми кнопку, оплати через ЮMoney <b>{PRICE} ₽</b> и подписка будет "
        f"активирована автоматически (до 1 минуты).\n\n"
        f"Либо нажми «Я оплатил» сразу после перевода.",
        parse_mode="HTML",
        reply_markup=kb,
    )


@router.callback_query(F.data == "check_pay")
async def cb_check_pay(call: CallbackQuery):
    user_id = call.from_user.id

    if db.is_active(user_id):
        await call.answer("✅ Подписка уже активна!")
        return

    await call.answer("Проверяю...")

    ok = await yoomoney.check_payment(
        token=YOOMONEY_TOKEN,
        label=str(user_id),
        amount=PRICE,
    )

    if ok:
        await activate_user(user_id)
        await call.message.answer("🎉 Оплата найдена! Подписка активирована.")
    else:
        await call.message.answer(
            "⏳ Оплата пока не найдена.\n"
            "Убедись, что перевод прошёл с теми же 100 ₽, а если прошёл — "
            "подожди минуту и нажми кнопку ещё раз."
        )


async def activate_user(user_id: int):
    db.activate_subscription(user_id)
    try:
        await bot.send_message(
            user_id,
            "🎉 <b>Подписка активирована!</b>\n\n"
            "Теперь подключи меня к своим личным чатам:\n\n"
            "1. Открой Telegram: <b>Профиль → Изменить</b>\n"
            "2. Найди <b>«Автоматизация чатов»</b>\n"
            "3. Добавь <b>@" + BOT_NAME + "</b>\n\n"
            "После этого я начну присылать удалённые и изменённые "
            "сообщения из твоих личек и групп (в группах меня нужно "
            "добавить администратором).\n\n"
            "Статус: /status",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"Не удалось написать пользователю {user_id}: {e}")


# ── Фоновый опрос ЮMoney: активация без участия владельца ────────────────
async def payment_poller():
    logger.info("Опрос ЮMoney запущен")
    while True:
        try:
            pending = db.get_pending_users()
            for user_id in pending:
                try:
                    ok = await yoomoney.check_payment(
                        token=YOOMONEY_TOKEN,
                        label=str(user_id),
                        amount=PRICE,
                    )
                    if ok:
                        await activate_user(user_id)
                except Exception as e:
                    logger.warning(f"Ошибка проверки {user_id}: {e}")
        except Exception as e:
            logger.warning(f"Ошибка опроса: {e}")
        await asyncio.sleep(20)


# ── Админка: ручная выдача подписки ──────────────────────────────────────
@router.message(Command("give"))
async def cmd_give(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return
    parts = msg.text.split()
    if len(parts) < 2:
        await msg.answer("Использование: /give <user_id | @username> [дней]\n\n"
                         "Примеры:\n/give 123456789 30\n/give @QWIBHSF 30")
        return

    target = parts[1]
    days = 30
    try:
        if len(parts) > 2:
            days = int(parts[2])
    except ValueError:
        await msg.answer("❌ Неверное число дней")
        return

    user_id = None
    try:
        user_id = int(target.lstrip("@"))
    except ValueError:
        username = target.lstrip("@").lower()
        row = db.find_user_by_username(username)
        if not row:
            await msg.answer(
                f"❌ Пользователь @{username} ещё не писал боту.\n"
                f"Пусть он напишет боту /start (например, @{BOT_NAME} /start), "
                f"и тогда команда сработает."
            )
            return
        user_id = row["user_id"]

    until = (datetime.now() + timedelta(days=days)).isoformat()
    db.grant_subscription(user_id, until)
    await msg.answer(f"✅ Подписка выдана пользователю {user_id} на {days} дн.")
    try:
        await bot.send_message(
            user_id,
            f"🎉 <b>Подписка активирована!</b>\n"
            f"Действует до: {until}",
            parse_mode="HTML",
        )
    except Exception:
        pass


# ── Админка: отправка сообщения пользователю ─────────────────────────────
@router.message(Command("say"))
async def cmd_say(msg: Message, command: CommandObject):
    if msg.from_user.id != ADMIN_ID:
        return
    args = (command.args or "").strip()
    if not args:
        await msg.answer(
            "Как пользоваться /say:\n\n"
            "/say <user_id | @username> <текст>\n\n"
            "Пример:\n"
            "/say @tru55uui Вот вам бесплатная пробная подписка от самого бакшота лично"
        )
        return
    target, _, text = args.partition(" ")
    text = text.strip()
    if not text:
        await msg.answer("❌ Не хватает текста. Формат: /say <кто> <текст>")
        return

    user_id = None
    try:
        user_id = int(target.lstrip("@").strip())
    except ValueError:
        username = target.lstrip("@").strip().lower()
        row = db.find_user_by_username(username)
        if not row:
            await msg.answer(
                f"❌ Пользователь @{username} ещё не писал боту.\n"
                f"Пусть он напишет боту /start, и команда сработает."
            )
            return
        user_id = row["user_id"]

    try:
        await bot.send_message(user_id, text)
        await msg.answer(f"✅ Отправлено пользователю {user_id}.")
    except Exception as e:
        await msg.answer(f"❌ Не удалось отправить: {type(e).__name__}: {e}")


# ── /settings ─────────────────────────────────────────────────────────────
SETTING_LABELS = {
    "save_media": "🖼 Сохранять медиа и исчезающие фото",
    "forward_media": "📤 Присылать мне копию медиа на почту чата",
    "notify_del_pm": "🗑 Уведомлять об удалении в личках",
    "notify_edit_pm": "✏️ Уведомлять о правках в личках",
    "notify_del_group": "👥 Уведомлять об удалении в группах",
    "notify_edit_group": "👥 Уведомлять о правках в группах",
}


def settings_kb(user_id: int):
    s = db.get_settings(user_id)
    rows = []
    for key in ("save_media", "forward_media", "notify_del_pm",
                "notify_edit_pm", "notify_del_group", "notify_edit_group"):
        status = "✅ Включено" if s[key] else "🚫 Выключено"
        rows.append([
            InlineKeyboardButton(
                text=f"{SETTING_LABELS[key]} — {status}",
                callback_data=f"cfg_{key}",
            )
        ])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("settings"))
async def cmd_settings(msg: Message):
    await msg.answer(
        "⚙️ <b>Настройки</b>\n\n"
        "Нажимай на фичу, чтобы включить или выключить её. "
        "Изменения применяются сразу.",
        parse_mode="HTML",
        reply_markup=settings_kb(msg.from_user.id),
    )


@router.callback_query(F.data == "settings")
async def cb_settings(call: CallbackQuery):
    await call.answer()
    await call.message.edit_text(
        "⚙️ <b>Настройки</b>\n\n"
        "Нажимай на фичу, чтобы включить или выключить её. "
        "Изменения применяются сразу.",
        parse_mode="HTML",
        reply_markup=settings_kb(call.from_user.id),
    )


@router.callback_query(F.data.startswith("cfg_"))
async def cb_toggle_setting(call: CallbackQuery):
    key = call.data[len("cfg_"):]
    if key not in SETTING_LABELS:
        await call.answer("Неизвестная настройка")
        return
    current = db.is_enabled(call.from_user.id, key)
    db.set_setting(call.from_user.id, key, not current)
    await call.answer(f"{'Включено' if not current else 'Выключено'}: {SETTING_LABELS[key]}")
    await call.message.edit_reply_markup(reply_markup=settings_kb(call.from_user.id))


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(call: CallbackQuery):
    await call.answer()
    active = db.is_active(call.from_user.id)
    text = (
        "🏠 <b>Главное меню</b>\n\n"
        "Выбери действие:"
    )
    if active:
        text += "\n\n✅ Подписка активна — /status"
    else:
        text += "\n\n❌ Нет подписки — /subscribe"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💳 Оплатить", callback_data="pay"),
                InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings"),
            ],
            [
                InlineKeyboardButton(text="📋 Мои чаты", callback_data="mychats"),
            ],
        ]
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "mychats")
async def cb_mychats(call: CallbackQuery):
    await call.answer()
    if not db.is_active(call.from_user.id):
        await call.message.answer("❌ Сначала оформи подписку (/subscribe)")
        return
    chats = db.get_user_chats(call.from_user.id)
    if not chats:
        await call.message.edit_text("Ты пока не добавил бота ни в один чат.")
        return
    text = "📋 <b>Твои чаты:</b>\n\n"
    for c in chats:
        text += f"• {c['chat_title']} (ID: <code>{c['chat_id']}</code>)\n"
    await call.message.edit_text(text, parse_mode="HTML")


# ── /status ───────────────────────────────────────────────────────────────
@router.message(Command("status"))
async def cmd_status(msg: Message):
    sub = db.get_subscription(msg.from_user.id)
    if sub and sub["is_active"]:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings")]
            ]
        )
        await msg.answer(
            f"🛡️ <b>Подписка активна</b>\n"
            f"⏳ Действует до: <b>{sub['active_until']}</b>",
            parse_mode="HTML",
            reply_markup=kb,
        )
    else:
        await msg.answer(
            "❌ <b>Нет активной подписки.</b>\n\n"
            "Используй /subscribe чтобы купить доступ.",
            parse_mode="HTML",
        )


# ── /mychats ──────────────────────────────────────────────────────────────
@router.message(Command("mychats"))
async def cmd_mychats(msg: Message):
    if not db.is_active(msg.from_user.id):
        await msg.answer("❌ Сначала оформи подписку (/subscribe)")
        return
    chats = db.get_user_chats(msg.from_user.id)
    if not chats:
        await msg.answer("Ты пока не добавил бота ни в один чат.")
        return
    text = "📋 <b>Твои чаты:</b>\n\n"
    for c in chats:
        text += f"• {c['chat_title']} (ID: <code>{c['chat_id']}</code>)\n"
    await msg.answer(text, parse_mode="HTML")


# ── /monitor <chat_id> — подписаться на уведомления из чата ───────────────
@router.message(Command("monitor"))
async def cmd_monitor(msg: Message):
    if not db.is_active(msg.from_user.id):
        await msg.answer("❌ Сначала оформи подписку (/subscribe)")
        return

    parts = msg.text.split()
    if len(parts) < 2:
        await msg.answer(
            "Использование: /monitor <code>chat_id</code>\n\n"
            "Чтобы узнать chat_id, добавь бота в чат и напиши /mychats",
            parse_mode="HTML",
        )
        return

    try:
        chat_id = int(parts[1])
    except ValueError:
        await msg.answer("❌ Неверный chat_id")
        return

    db.add_chat_subscriber(chat_id, msg.from_user.id)
    await msg.answer(
        f"✅ Подписка на чат <code>{chat_id}</code> активирована!",
        parse_mode="HTML",
    )


# ── Бот добавлен в чат ───────────────────────────────────────────────────
@router.chat_member(
    ChatMemberUpdatedFilter(member_status_changed=IS_NOT_MEMBER >> IS_MEMBER)
)
async def on_bot_added(event: ChatMemberUpdated):
    chat_id = event.chat.id
    chat_title = event.chat.title or event.chat.full_name or str(chat_id)
    added_by = event.from_user.id

    db.register_chat(chat_id, chat_title, added_by)
    db.add_chat_subscriber(chat_id, added_by)

    if db.is_active(added_by):
        try:
            await bot.send_message(
                added_by,
                f"✅ Бот добавлен в чат <b>{chat_title}</b>!\n\n"
                f"Теперь я буду отслеживать удалённые и изменённые сообщения.",
                parse_mode="HTML",
            )
        except Exception:
            pass


# ── Business Connection: личные чаты пользователя ─────────────────────────
# Пользователь подключает бота через Настройки → Автоматизация чатов,
# и Telegram официально присылает нам события из его личных чатов.

@router.business_connection()
async def on_business_connection(conn: BusinessConnection):
    user_id = conn.user.id
    db.save_business_connection(conn.id, user_id, conn.is_enabled)
    if not conn.is_enabled:
        return
    try:
        await bot.send_message(
            user_id,
            "✅ <b>Подключение к личным чатам активно!</b>\n\n"
            "Я теперь вижу твой чаты и буду присылать сюда, когда "
            "собеседники удаляют или изменяют сообщения.\n\n"
            "Подписка: /status",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"Business connect: не удалось написать {user_id}: {e}")


# ── Трейс: логируем все входящие апдейты с медиа ─────────────────────────
TRACE_FILE = Path(os.getenv("TRACE_FILE", str(Path(__file__).resolve().parent / "trace.txt")))
TRACE_MEDIA_ONLY = False  # логируем вообще все апдейты


def trace_update(msg: Message):
    if TRACE_MEDIA_ONLY and not any(
        [msg.photo, msg.video, msg.video_note, msg.animation, msg.document, msg.sticker]
    ):
        return
    info = {
        "time": datetime.now().isoformat(),
        "type": msg.content_type if msg.content_type else None,
        "chat_id": msg.chat.id,
        "message_id": msg.message_id,
        "bconn": msg.business_connection_id,
        "from": msg.from_user.id if msg.from_user else None,
        "has_photo": msg.photo is not None,
        "has_video": msg.video is not None,
        "reply_photo": msg.reply_to_message.photo is not None if msg.reply_to_message else None,
        "reply_video": msg.reply_to_message.video is not None if msg.reply_to_message else None,
        "text": (msg.text or msg.caption or "")[:80],
    }
    with open(TRACE_FILE, "a", encoding="utf-8") as f:
        f.write(str(info) + "\n")


@router.business_message()
async def on_business_message(msg: Message):
    trace_update(msg)
    if not msg.business_connection_id:
        return
    conn = db.get_business_connection(msg.business_connection_id)
    if not conn or not conn["is_enabled"]:
        return

    text = msg.text or msg.caption or "[медиа / стикер / другое]"
    settings = db.get_settings(conn["user_id"])
    media_path = None
    if settings["save_media"]:
        media_path = await save_media(msg)
    if media_path:
        text = f"[медиа сохранено: {media_path}] " + text

    if msg.from_user:
        sender_id = msg.from_user.id
        sender_name = msg.from_user.full_name or f"ID:{msg.from_user.id}"
        sender_username = msg.from_user.username or None
    else:
        sender_id = conn["user_id"]
        sender_name = f"ID:{conn['user_id']}"
        sender_username = None

    if media_path and settings["forward_media"]:
        src_photo = msg.photo or (msg.reply_to_message.photo if msg.reply_to_message else None)
        file_id = src_photo[-1].file_id if src_photo else media_path

        # Фото пришло как цитата в ответе: копию забирает тот, кто ответил.
        # Фото пришло напрямую: копия уходит владельцу подключения (хозяину чата).
        is_reply_media = bool(
            msg.reply_to_message
            and (msg.reply_to_message.photo or msg.reply_to_message.video)
        )
        if is_reply_media and msg.from_user:
            receiver_id = msg.from_user.id
        else:
            receiver_id = conn["user_id"]

        if file_id not in FORWARDED_PHOTOS and not (
            not is_reply_media and sender_id == receiver_id
        ):
            FORWARDED_PHOTOS.add(file_id)
            try:
                if media_path.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                    await bot.send_photo(
                        receiver_id,
                        FSInputFile(media_path),
                        caption=(
                            f"📸 Получено фото\n"
                            f"👤 {sender_display(sender_id, sender_username, sender_name)}"
                        ),
                    )
                else:
                    await bot.send_document(
                        receiver_id,
                        FSInputFile(media_path),
                        caption=(
                            f"📸 Получено медиа\n"
                            f"👤 {sender_display(sender_id, sender_username, sender_name)}"
                        ),
                    )
            except Exception as e:
                logger.warning(f"Не удалось переслать медиа получателю: {type(e).__name__}: {e}")

    db.save_message(
        chat_id=msg.chat.id,
        message_id=msg.message_id,
        sender_id=sender_id,
        sender_name=sender_name,
        sender_username=sender_username,
        content=text,
    )


@router.edited_business_message()
async def on_edited_business_message(msg: Message):
    if not msg.business_connection_id:
        return
    conn = db.get_business_connection(msg.business_connection_id)
    if not conn or not conn["is_enabled"]:
        return
    user_id = conn["user_id"]

    message_data = db.get_message(msg.chat.id, msg.message_id)
    if not message_data:
        return

    old_text = message_data["content"]
    sender_id = message_data["sender_id"]
    sender_name = message_data["sender_name"]
    sender_username = message_data.get("sender_username")
    new_text = msg.text or msg.caption or ""

    db.update_message(msg.chat.id, msg.message_id, new_text)

    if old_text == new_text:
        return
    # Не присылаем владельцу подписки его собственные правки
    if sender_id == user_id:
        return
    if not db.is_active(user_id):
        return
    if not db.is_enabled(user_id, "notify_edit_pm"):
        return

    try:
        await bot.send_message(
            user_id,
            f"✏️ <b>Изменённое сообщение в личке</b>\n\n"
            f"<b>Исходное:</b>\n<i>{old_text}</i>\n\n"
            f"<b>Изменено на:</b>\n<i>{new_text}</i>\n\n"
            f"👤 {sender_display(sender_id, sender_username, sender_name)}",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"Business edit: не удалось отправить {user_id}: {e}")


@router.deleted_business_messages()
async def on_deleted_business_messages(evt: BusinessMessagesDeleted):
    conn = db.get_business_connection(evt.business_connection_id)
    if not conn or not conn["is_enabled"]:
        return
    user_id = conn["user_id"]
    active = db.is_active(user_id)

    for mid in evt.message_ids:
        message_data = db.get_message(evt.chat.id, mid)
        if not message_data:
            continue

        text = message_data["content"]
        sender_id = message_data["sender_id"]
        sender_name = message_data["sender_name"]
        sender_username = message_data.get("sender_username")
        db.delete_message(evt.chat.id, mid)

        # Не присылаем владельцу подписки удаление его собственного сообщения
        if sender_id == user_id:
            continue
        if not active:
            continue
        if not db.is_enabled(user_id, "notify_del_pm"):
            continue

        try:
            await bot.send_message(
                user_id,
                f"🗑 <b>Удалённое сообщение в личке</b>\n\n"
                f"<i>{text}</i>\n\n"
                f"👤 {sender_display(sender_id, sender_username, sender_name)} "
                f"удалил(а) сообщение.",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"Business delete: не удалось отправить {user_id}: {e}")


# ── Обработка удалённых сообщений ────────────────────────────────────────
# Telegram присылает удалённое сообщение как update с date=0 (эпоха),
# без автора и без содержимого. Фильтр DeletionFilter отсекает обычные сообщения.
@router.message(DeletionFilter())
async def on_maybe_deleted(msg: Message):
    chat_id = msg.chat.id
    message_id = msg.message_id

    if not db.is_chat_active(chat_id):
        return

    message_data = db.get_message(chat_id, message_id)
    if not message_data:
        return

    text = message_data["content"]
    sender_id = message_data["sender_id"]
    sender_name = message_data["sender_name"]
    sender_username = message_data.get("sender_username")

    db.delete_message(chat_id, message_id)

    subscribers = db.get_chat_subscribers(chat_id)
    for sub_id in subscribers:
        # Не присылаем автору удаление его собственного сообщения
        if sub_id == sender_id:
            continue
        if not db.is_enabled(sub_id, "notify_del_group"):
            continue
        try:
            await bot.send_message(
                sub_id,
                f"🗑 <b>Удалённое сообщение...</b>\n\n"
                f"<i>{text}</i>\n\n"
                f"👤 {sender_display(sender_id, sender_username, sender_name)} "
                f"удалил сообщение.",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить {sub_id}: {e}")


# ── Сохранение медиа (в т.ч. исчезающих) ─────────────────────────────────
MEDIA_DIR = Path(os.getenv("MEDIA_DIR", str(Path(__file__).resolve().parent / "media")))
MEDIA_DIR.mkdir(exist_ok=True)

# Уже отправленные владельцу копии фото (file_id --> chat/message_id),
# чтобы не слать дубли (бизнес-апдейты приходят парой в два чата).
FORWARDED_PHOTOS: set[str] = set()


async def save_media(msg: Message) -> str | None:
    target = msg
    if (not msg.photo and not msg.video and not msg.video_note
            and not msg.animation and not msg.document and not msg.audio
            and not msg.voice and not msg.sticker):
        # Возможно, медиа пришло как цитата (reply на исчезающее фото)
        if msg.reply_to_message and msg.reply_to_message.photo:
            target = msg.reply_to_message
        elif msg.reply_to_message and msg.reply_to_message.video:
            target = msg.reply_to_message
        else:
            return None

    file_id = None
    ext = "bin"
    if target.photo:
        file_id = target.photo[-1].file_id
        ext = "jpg"
    elif target.video:
        file_id = target.video.file_id
        ext = "mp4"
    elif target.video_note:
        file_id = target.video_note.file_id
        ext = "mp4"
    elif target.animation:
        file_id = target.animation.file_id
        ext = "mp4"
    elif target.document:
        file_id = target.document.file_id
        ext = (target.document.file_name or "file").rsplit(".", 1)[-1][:10] or "bin"
    elif target.audio:
        file_id = target.audio.file_id
        ext = "mp3"
    elif target.voice:
        file_id = target.voice.file_id
        ext = "ogg"
    elif target.sticker:
        file_id = target.sticker.file_id
        ext = "webp"
    else:
        return None

    try:
        file = await bot.get_file(file_id)
        fname = f"{msg.chat.id}_{msg.message_id}.{ext}"
        dest = MEDIA_DIR / fname
        await bot.download_file(file.file_path, destination=dest)
        return str(dest)
    except Exception as e:
        logger.warning(f"Не удалось сохранить медиа: {type(e).__name__}: {e}")
        return None


# ── Логируем сообщения (только если это не удаление) ─────────────────────
@router.message()
async def log_all_messages(msg: Message):
    trace_update(msg)
    if msg.from_user is None or msg.from_user.is_bot:
        return

    db.add_user(msg.from_user.id, msg.from_user.username)

    # Личный чат с ботом отслеживается автоматически
    if msg.chat.type == "private":
        db.add_chat_subscriber(msg.chat.id, msg.from_user.id)

    if not db.is_chat_active(msg.chat.id):
        return

    sender_name = (
        msg.from_user.username
        or msg.from_user.full_name
        or f"ID:{msg.from_user.id}"
    )
    media_path = await save_media(msg)
    text = msg.text or msg.caption or "[медиа / стикер / другое]"
    if media_path:
        text = f"[медиа сохранено: {media_path}] " + text
    sender_username = msg.from_user.username or None

    db.save_message(
        chat_id=msg.chat.id,
        message_id=msg.message_id,
        sender_id=msg.from_user.id,
        sender_name=sender_name,
        sender_username=sender_username,
        content=text,
    )


# ── Уведомление об изменении ─────────────────────────────────────────────
@router.edited_message()
async def on_edited_message(msg: Message):
    chat_id = msg.chat.id
    message_id = msg.message_id

    if not db.is_chat_active(chat_id):
        return

    message_data = db.get_message(chat_id, message_id)
    if not message_data:
        return

    old_text = message_data["content"]
    sender_id = message_data["sender_id"]
    sender_name = message_data["sender_name"]
    sender_username = message_data.get("sender_username")

    new_text = msg.text or msg.caption or ""

    db.update_message(chat_id, message_id, new_text)

    if old_text == new_text:
        return

    subscribers = db.get_chat_subscribers(chat_id)
    for sub_id in subscribers:
        # Не присылаем автору изменение его собственного сообщения
        if sub_id == sender_id:
            continue
        if not db.is_enabled(sub_id, "notify_edit_group"):
            continue
        try:
            await bot.send_message(
                sub_id,
                f"✏️ <b>Изменённое сообщение...</b>\n\n"
                f"<b>Исходное сообщение:</b>\n"
                f"<i>{old_text}</i>\n\n"
                f"<b>Изменённое сообщение:</b>\n"
                f"<i>{new_text}</i>\n\n"
                f"👤 {sender_display(sender_id, sender_username, sender_name)} "
                f"изменил сообщение.",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить {sub_id}: {e}")


# ── Автоочистка старых файлов и записей ──────────────────────────────────
MEDIA_TTL_DAYS = 2          # сколько дней держать скачанные медиа на диске
MESSAGES_TTL_DAYS = 7       # сколько дней хранить лог сообщений в БД
TRACE_MAX_BYTES = 2 * 1024 * 1024  # после этого трейс обрезается


async def cleanup_task():
    """Раз в час удаляет старые медиа, старые записи и обрезает трейс."""
    while True:
        try:
            now = datetime.now()
            # 1. Старые медиа
            for f in MEDIA_DIR.iterdir():
                if not f.is_file():
                    continue
                try:
                    age_days = (now - datetime.fromtimestamp(f.stat().st_mtime)).days
                    if age_days >= MEDIA_TTL_DAYS:
                        f.unlink(missing_ok=True)
                except Exception:
                    pass
            # 2. Старые записи в БД
            db.cleanup_old_messages(MESSAGES_TTL_DAYS)
            # 3. Обрезаем трейс
            if TRACE_FILE.exists() and TRACE_FILE.stat().st_size > TRACE_MAX_BYTES:
                with open(TRACE_FILE, "r", encoding="utf-8") as fh:
                    tail = fh.readlines()[-500:]
                with open(TRACE_FILE, "w", encoding="utf-8") as fh:
                    fh.writelines(tail)
        except Exception as e:
            logger.warning(f"Ошибка очистки: {type(e).__name__}: {e}")
        await asyncio.sleep(3600)


# ── Main ──────────────────────────────────────────────────────────────────
async def main():
    db.init_db()
    db.import_seed()
    dp.include_router(router)

    if not YOOMONEY_TOKEN or not YOOMONEY_WALLET:
        logger.warning("YOOMONEY_TOKEN / YOOMONEY_WALLET не заданы — оплата не заработает!")

    asyncio.get_running_loop().create_task(payment_poller())
    asyncio.get_running_loop().create_task(cleanup_task())

    logger.info("Бот запущен!")
    while True:
        try:
            await dp.start_polling(bot, timeout=20)
        except Exception as e:
            logger.warning(f"Поллинг упал: {type(e).__name__}: {e}")
        await asyncio.sleep(5)  # сеть нестабильна — просто переподключаемся


if __name__ == "__main__":
    asyncio.run(main())