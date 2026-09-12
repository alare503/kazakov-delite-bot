import json
import os
import sqlite3
from datetime import datetime, timedelta

DB_PATH = os.getenv("DB_PATH", "messages.db")


def import_seed(seed_path=None):
    """Перенос данных с локальной базы на новую.

    - Подписки пользователей: только один раз (метка в app_meta).
    - Business-подключения и привязки чатов: при каждом старте,
      безопасно (INSERT OR IGNORE) — без них бот не видит удаляемые сообщения.
    """
    if seed_path is None:
        seed_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed.json")
    if not os.path.exists(seed_path):
        return
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    done = c.execute("SELECT value FROM app_meta WHERE key = 'seed_imported'").fetchone()
    with open(seed_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not done:
        # Пользователи и подписки — только один раз
        now = datetime.now()
        for row in data.get("users", []):
            uid = row["user_id"]
            until = row.get("active_until")
            cur = c.execute(
                "SELECT is_active, active_until FROM users WHERE user_id = ?", (uid,)
            ).fetchone()
            live = cur and cur[0] and cur[1] and datetime.fromisoformat(cur[1]) > now
            if live:
                continue
            c.execute(
                "INSERT INTO users (user_id, username, is_active, active_until, receipt_pending, receipt_sent) "
                "VALUES (?, ?, 1, ?, 0, 0) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "is_active = 1, active_until = excluded.active_until, receipt_pending = 0, receipt_sent = 0",
                (uid, row.get("username"), until),
            )
        c.execute(
            "INSERT OR REPLACE INTO app_meta (key, value) VALUES ('seed_imported', '1')"
        )

    # Business-подключения (без них бот не знает, из чьего аккаунта апдейты)
    for row in data.get("business_connections", []):
        c.execute(
            "INSERT OR IGNORE INTO business_connections "
            "(business_connection_id, user_id, is_enabled, connected_at) VALUES (?, ?, ?, ?)",
            (row["business_connection_id"], row["user_id"], 1 if row.get("is_enabled") else 0, row.get("connected_at")),
        )

    # Привязки чат -> подписчик
    for row in data.get("chat_subscribers", []):
        c.execute(
            "INSERT OR IGNORE INTO chat_subscribers (chat_id, user_id) VALUES (?, ?)",
            (row["chat_id"], row["user_id"]),
        )

    conn.commit()
    conn.close()


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            is_active INTEGER DEFAULT 0,
            active_until TEXT,
            receipt_pending INTEGER DEFAULT 0,
            receipt_sent INTEGER DEFAULT 0
        )
    """)

    cols = [r[1] for r in c.execute("PRAGMA table_info(users)")]
    if "username" not in cols:
        c.execute("ALTER TABLE users ADD COLUMN username TEXT")

    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            chat_id INTEGER,
            message_id INTEGER,
            sender_id INTEGER,
            sender_name TEXT,
            sender_username TEXT,
            content TEXT,
            saved_at TEXT,
            PRIMARY KEY (chat_id, message_id)
        )
    """)

    msg_cols = [r[1] for r in c.execute("PRAGMA table_info(messages)")]
    if "sender_username" not in msg_cols:
        c.execute("ALTER TABLE messages ADD COLUMN sender_username TEXT")

    c.execute("""
        CREATE TABLE IF NOT EXISTS chat_subscribers (
            chat_id INTEGER,
            user_id INTEGER,
            PRIMARY KEY (chat_id, user_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS chat_admins (
            chat_id INTEGER PRIMARY KEY,
            chat_title TEXT,
            added_by INTEGER
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS business_connections (
            business_connection_id TEXT PRIMARY KEY,
            user_id INTEGER,
            is_enabled INTEGER DEFAULT 1,
            connected_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            save_media INTEGER DEFAULT 1,
            forward_media INTEGER DEFAULT 1,
            notify_del_pm INTEGER DEFAULT 1,
            notify_edit_pm INTEGER DEFAULT 1,
            notify_del_group INTEGER DEFAULT 1,
            notify_edit_group INTEGER DEFAULT 1
        )
    """)

    conn.commit()
    conn.close()


# ── Users ─────────────────────────────────────────────────────────────────

def add_user(user_id, username=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO users (user_id, username, is_active) VALUES (?, ?, 0)",
        (user_id, username),
    )
    if username:
        c.execute(
            "UPDATE users SET username = ? WHERE user_id = ? AND username IS NULL",
            (username, user_id),
        )
    conn.commit()
    conn.close()


def find_user_by_username(username):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def is_active(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return False
    if not row["is_active"]:
        return False
    if row["active_until"]:
        until = datetime.fromisoformat(row["active_until"])
        if until < datetime.now():
            return False
    return True


def get_subscription(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def activate_subscription(user_id):
    until = (datetime.now() + timedelta(days=30)).isoformat()
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "UPDATE users SET is_active = 1, active_until = ?, receipt_pending = 0, receipt_sent = 0 WHERE user_id = ?",
        (until, user_id),
    )
    conn.commit()
    conn.close()


def grant_subscription(user_id, until):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO users (user_id, is_active, active_until, receipt_pending, receipt_sent) "
        "VALUES (?, 1, ?, 0, 0) "
        "ON CONFLICT(user_id) DO UPDATE SET "
        "is_active = 1, active_until = excluded.active_until, receipt_pending = 0, receipt_sent = 0",
        (user_id, until),
    )
    conn.commit()
    conn.close()


def mark_receipt_pending(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "UPDATE users SET receipt_pending = 1 WHERE user_id = ?",
        (user_id,),
    )
    conn.commit()
    conn.close()


def get_pending_users():
    """Возвращает список user_id со статусом «ждём оплату»."""
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT user_id FROM users WHERE receipt_pending = 1 AND is_active = 0"
    )
    rows = c.fetchall()
    conn.close()
    return [r["user_id"] for r in rows]


def is_pending_receipt(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT receipt_pending FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row and row["receipt_pending"]:
        return True
    return False


def mark_receipt_sent(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "UPDATE users SET receipt_pending = 1, receipt_sent = 1 WHERE user_id = ?",
        (user_id,),
    )
    conn.commit()
    conn.close()


# ── Messages ──────────────────────────────────────────────────────────────

def save_message(chat_id, message_id, sender_id, sender_name, content, sender_username=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO messages (chat_id, message_id, sender_id, sender_name, sender_username, content, saved_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (chat_id, message_id, sender_id, sender_name, sender_username, content, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_message(chat_id, message_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM messages WHERE chat_id = ? AND message_id = ?",
        (chat_id, message_id),
    )
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def update_message(chat_id, message_id, content, saved_at=None):
    conn = get_conn()
    c = conn.cursor()
    if saved_at is None:
        saved_at = datetime.now().isoformat()
    c.execute(
        "UPDATE messages SET content = ?, saved_at = ? WHERE chat_id = ? AND message_id = ?",
        (content, saved_at, chat_id, message_id),
    )
    conn.commit()
    conn.close()


def delete_message(chat_id, message_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "DELETE FROM messages WHERE chat_id = ? AND message_id = ?",
        (chat_id, message_id),
    )
    conn.commit()
    conn.close()


# ── Chat subscribers ──────────────────────────────────────────────────────

def add_chat_subscriber(chat_id, user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO chat_subscribers (chat_id, user_id) VALUES (?, ?)",
        (chat_id, user_id),
    )
    conn.commit()
    conn.close()


def get_chat_subscribers(chat_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT cs.user_id FROM chat_subscribers cs "
        "JOIN users u ON cs.user_id = u.user_id "
        "WHERE cs.chat_id = ? AND u.is_active = 1",
        (chat_id,),
    )
    rows = c.fetchall()
    conn.close()
    return [r["user_id"] for r in rows]


def is_chat_active(chat_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT COUNT(*) as cnt FROM chat_subscribers cs "
        "JOIN users u ON cs.user_id = u.user_id "
        "WHERE cs.chat_id = ? AND u.is_active = 1",
        (chat_id,),
    )
    row = c.fetchone()
    conn.close()
    return row["cnt"] > 0


def get_user_chats(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT chat_id, chat_title FROM chat_admins WHERE added_by = ?",
        (user_id,),
    )
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def register_chat(chat_id, chat_title, added_by):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO chat_admins (chat_id, chat_title, added_by)
        VALUES (?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            chat_title = excluded.chat_title,
            added_by = excluded.added_by
        """,
        (chat_id, chat_title, added_by),
    )
    conn.commit()
    conn.close()


# ── Business Connection (линые чаты пользователя) ─────────────────────────

def save_business_connection(business_connection_id, user_id, is_enabled):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO business_connections (business_connection_id, user_id, is_enabled, connected_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(business_connection_id) DO UPDATE SET
            user_id = excluded.user_id,
            is_enabled = excluded.is_enabled,
            connected_at = excluded.connected_at
        """,
        (business_connection_id, user_id, 1 if is_enabled else 0, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_business_connection(business_connection_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM business_connections WHERE business_connection_id = ?",
        (business_connection_id,),
    )
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def remove_business_connection(business_connection_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "DELETE FROM business_connections WHERE business_connection_id = ?",
        (business_connection_id,),
    )
    conn.commit()
    conn.close()


# ── User settings (per-feature on/off) ────────────────────────────────────

DEFAULT_SETTINGS = {
    "save_media": 1,
    "forward_media": 1,
    "notify_del_pm": 1,
    "notify_edit_pm": 1,
    "notify_del_group": 1,
    "notify_edit_group": 1,
}


def get_settings(user_id):
    """Возвращает dict настроек пользователя. Несуществующие приходят как DEFAULT_SETTINGS."""
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT user_id, save_media, forward_media, notify_del_pm, notify_edit_pm, "
        "notify_del_group, notify_edit_group FROM user_settings WHERE user_id = ?",
        (user_id,),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return dict(DEFAULT_SETTINGS)
    return {
        "save_media": row["save_media"],
        "forward_media": row["forward_media"],
        "notify_del_pm": row["notify_del_pm"],
        "notify_edit_pm": row["notify_edit_pm"],
        "notify_del_group": row["notify_del_group"],
        "notify_edit_group": row["notify_edit_group"],
    }


def set_setting(user_id, key, value):
    """Включает/выключает одну фичу. key должен быть среди DEFAULT_SETTINGS."""
    if key not in DEFAULT_SETTINGS:
        raise ValueError(f"Неизвестная настройка: {key}")
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO user_settings (user_id, save_media, forward_media, notify_del_pm,
                                   notify_edit_pm, notify_del_group, notify_edit_group)
        VALUES (?, 1, 1, 1, 1, 1, 1)
        ON CONFLICT(user_id) DO NOTHING
        """,
        (user_id,),
    )
    c.execute(
        f"UPDATE user_settings SET {key} = ? WHERE user_id = ?",
        (1 if value else 0, user_id),
    )
    conn.commit()
    conn.close()


def is_enabled(user_id, key):
    """Проверяет, включена ли фича (удобная обёртка)."""
    return bool(get_settings(user_id).get(key))


def cleanup_old_messages(days):
    """Удаляет из messages записи старше days дней."""
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM messages WHERE saved_at < ?", (cutoff,))
    conn.commit()
    conn.close()
