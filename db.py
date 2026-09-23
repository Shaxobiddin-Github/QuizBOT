"""SQLite baza — ikkala rejim uchun umumiy."""
from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

import aiosqlite

import config

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    full_name   TEXT,
    username    TEXT,
    created_at  TEXT,
    last_seen   TEXT
);

CREATE TABLE IF NOT EXISTS collections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT DEFAULT '',
    owner_id    INTEGER,
    is_default  INTEGER DEFAULT 0,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS questions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    text          TEXT NOT NULL,
    options       TEXT NOT NULL,
    correct       INTEGER NOT NULL,
    explanation   TEXT DEFAULT '',
    fingerprint   TEXT,
    created_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_q_collection ON questions(collection_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_q_fingerprint ON questions(collection_id, fingerprint);

CREATE TABLE IF NOT EXISTS sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id      INTEGER,
    chat_id       INTEGER,
    collection_id INTEGER,
    mode          TEXT,
    q_ids         TEXT,
    cursor        INTEGER DEFAULT 0,
    status        TEXT DEFAULT 'active',
    settings      TEXT DEFAULT '{}',
    started_at    TEXT,
    finished_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_s_owner ON sessions(owner_id, status);

CREATE TABLE IF NOT EXISTS answers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    user_id     INTEGER,
    user_name   TEXT,
    question_id INTEGER,
    q_index     INTEGER,
    chosen      INTEGER,
    is_correct  INTEGER,
    spent_ms    INTEGER DEFAULT 0,
    created_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_a_session ON answers(session_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_a_unique ON answers(session_id, user_id, q_index);

CREATE TABLE IF NOT EXISTS learned (
    user_id     INTEGER,
    question_id INTEGER,
    created_at  TEXT,
    PRIMARY KEY (user_id, question_id)
);

CREATE TABLE IF NOT EXISTS chats (
    chat_id    INTEGER PRIMARY KEY,
    title      TEXT,
    type       TEXT,
    added_at   TEXT,
    last_seen  TEXT
);

CREATE TABLE IF NOT EXISTS chat_members (
    chat_id    INTEGER,
    user_id    INTEGER,
    last_seen  TEXT,
    PRIMARY KEY (chat_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_cm_user ON chat_members(user_id);

CREATE TABLE IF NOT EXISTS collection_shares (
    collection_id INTEGER REFERENCES collections(id) ON DELETE CASCADE,
    chat_id       INTEGER,
    created_at    TEXT,
    PRIMARY KEY (collection_id, chat_id)
);
CREATE INDEX IF NOT EXISTS idx_cs_chat ON collection_shares(chat_id);

CREATE TABLE IF NOT EXISTS sent_messages (
    chat_id    INTEGER,
    message_id INTEGER,
    kind       TEXT,
    file_id    TEXT DEFAULT '',
    file_name  TEXT DEFAULT '',
    caption    TEXT DEFAULT '',
    pinned     INTEGER DEFAULT 0,
    keep       INTEGER DEFAULT 0,
    sent_at    TEXT,
    PRIMARY KEY (chat_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_sent_time ON sent_messages(sent_at);
CREATE INDEX IF NOT EXISTS idx_sent_chat ON sent_messages(chat_id, kind);

CREATE TABLE IF NOT EXISTS bot_settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS prefs (
    user_id       INTEGER PRIMARY KEY,
    collection_id INTEGER,
    count         INTEGER DEFAULT 20,
    timer         INTEGER DEFAULT 30,
    shuffle_q     INTEGER DEFAULT 1,
    shuffle_a     INTEGER DEFAULT 1,
    instant       INTEGER DEFAULT 1,
    skip_learned  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS media_cache (
    key        TEXT PRIMARY KEY,
    file_id    TEXT NOT NULL,
    created_at TEXT
);
"""

_conn: aiosqlite.Connection | None = None


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fingerprint(text: str, options: Sequence[str], image: str = "",
                option_images: Sequence[str] = ()) -> str:
    raw = text.strip().lower() + "||" + "|".join(sorted(o.strip().lower() for o in options))
    if image or option_images:
        # rasmli savollarda matn bir xil bo'lishi mumkin — rasmlar ham hisobga olinadi
        raw += "||img:" + image + "|" + "|".join(option_images)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


async def connect() -> aiosqlite.Connection:
    global _conn
    if _conn is None:
        _conn = await aiosqlite.connect(config.DB_PATH)
        _conn.row_factory = aiosqlite.Row
        await _conn.executescript(SCHEMA)
        await _migrate(_conn)
        await _conn.commit()
    return _conn


async def _migrate(conn: aiosqlite.Connection) -> None:
    """Eski bazani yangi ustunlarga moslash (orqaga mos, xavfsiz)."""
    async with conn.execute("PRAGMA table_info(collections)") as cur:
        cols = {r["name"] for r in await cur.fetchall()}
    if "visibility" not in cols:
        # private | groups | public
        await conn.execute(
            "ALTER TABLE collections ADD COLUMN visibility TEXT DEFAULT 'private'")
        # Mavjud default baza allaqachon hamma ishlatayotgani uchun ochiq qoladi —
        # egasi xohlagan payt bir tugma bilan yopadi.
        await conn.execute(
            "UPDATE collections SET visibility='public' WHERE is_default=1")
        await conn.execute(
            "UPDATE collections SET visibility='private' WHERE is_default=0")
    if "kind" not in cols:
        await conn.execute(
            "ALTER TABLE collections ADD COLUMN kind TEXT DEFAULT 'quiz'")
    async with conn.execute("PRAGMA table_info(questions)") as cur:
        qcols = {r["name"] for r in await cur.fetchall()}
    for col, ddl in (("difficulty", "INTEGER DEFAULT 2"),
                     ("category", "TEXT DEFAULT ''"),
                     ("image", "TEXT DEFAULT ''"),
                     ("option_images", "TEXT DEFAULT ''")):
        if col not in qcols:
            await conn.execute(f"ALTER TABLE questions ADD COLUMN {col} {ddl}")
    async with conn.execute("PRAGMA table_info(sent_messages)") as cur:
        smcols = {r["name"] for r in await cur.fetchall()}
    if "author" not in smcols:
        await conn.execute("ALTER TABLE sent_messages ADD COLUMN author TEXT DEFAULT ''")
    async with conn.execute("PRAGMA table_info(chats)") as cur:
        chcols = {r["name"] for r in await cur.fetchall()}
    for col in ("username", "invite_link"):
        if col not in chcols:
            await conn.execute(f"ALTER TABLE chats ADD COLUMN {col} TEXT DEFAULT ''")
    async with conn.execute("PRAGMA table_info(users)") as cur:
        ucols = {r["name"] for r in await cur.fetchall()}
    if "blocked" not in ucols:
        await conn.execute("ALTER TABLE users ADD COLUMN blocked INTEGER DEFAULT 0")
    await conn.execute(
        """UPDATE collections SET owner_id=(SELECT user_id FROM users
                                            ORDER BY created_at LIMIT 1)
           WHERE is_default=1 AND owner_id IS NULL""")
    await conn.commit()


async def close() -> None:
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None


async def fetch_all(sql: str, params: Iterable[Any] = ()) -> list[aiosqlite.Row]:
    conn = await connect()
    async with conn.execute(sql, tuple(params)) as cur:
        return list(await cur.fetchall())


async def fetch_one(sql: str, params: Iterable[Any] = ()) -> aiosqlite.Row | None:
    conn = await connect()
    async with conn.execute(sql, tuple(params)) as cur:
        return await cur.fetchone()


async def execute(sql: str, params: Iterable[Any] = ()) -> int:
    conn = await connect()
    cur = await conn.execute(sql, tuple(params))
    await conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------- users / prefs
async def touch_user(user_id: int, full_name: str, username: str | None) -> None:
    await execute(
        """INSERT INTO users(user_id, full_name, username, created_at, last_seen)
           VALUES(?,?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
             full_name=excluded.full_name,
             username=excluded.username,
             last_seen=excluded.last_seen""",
        (user_id, full_name, username or "", now(), now()),
    )


async def set_blocked(user_id: int, blocked: bool = True) -> None:
    await execute("UPDATE users SET blocked=? WHERE user_id=?", (int(blocked), user_id))


async def broadcast_users() -> list[int]:
    rows = await fetch_all(
        "SELECT user_id FROM users WHERE COALESCE(blocked,0)=0 ORDER BY user_id")
    return [r["user_id"] for r in rows]


async def broadcast_groups() -> list[aiosqlite.Row]:
    return await fetch_all(
        """SELECT chat_id, title FROM chats
           WHERE type IN ('group','supergroup') ORDER BY last_seen DESC""")


# ------------------------------------------------- bot yuborgan xabarlar
FILE_KINDS = ("document", "photo", "video", "audio", "voice", "animation")


async def record_sent(chat_id: int, message_id: int, kind: str, file_id: str = "",
                      file_name: str = "", caption: str = "", author: str = "",
                      keep: int = 0) -> None:
    """Guruhdagi xabarni ro'yxatga oladi.

    `author` bo'sh bo'lsa — xabarni bot yuborgan. `keep=1` bo'lsa avtomatik
    tozalash bu xabarga tegmaydi (a'zolar yuborgan fayllar shunday saqlanadi).
    """
    await execute(
        """INSERT INTO sent_messages(chat_id, message_id, kind, file_id, file_name,
                                     caption, author, keep, sent_at)
           VALUES(?,?,?,?,?,?,?,?,?)
           ON CONFLICT(chat_id, message_id) DO NOTHING""",
        (chat_id, message_id, kind, file_id or "", (file_name or "")[:200],
         (caption or "")[:300], (author or "")[:100], keep, now()))


async def mark_pinned(chat_id: int, message_id: int) -> None:
    """Qadalgan xabarni belgilaydi (yozuv bo'lmasa — yaratadi)."""
    await execute(
        """INSERT INTO sent_messages(chat_id, message_id, kind, pinned, keep, sent_at)
           VALUES(?,?,'copy',1,1,?)
           ON CONFLICT(chat_id, message_id) DO UPDATE SET pinned=1, keep=1""",
        (chat_id, message_id, now()))


async def forget_message(chat_id: int, message_id: int) -> None:
    await execute("DELETE FROM sent_messages WHERE chat_id=? AND message_id=?",
                  (chat_id, message_id))


async def chat_files(chat_id: int, limit: int = 50) -> list[aiosqlite.Row]:
    marks = ",".join("?" * len(FILE_KINDS))
    return await fetch_all(
        f"""SELECT * FROM sent_messages
            WHERE chat_id=? AND kind IN ({marks})
            ORDER BY sent_at DESC LIMIT ?""",
        (chat_id, *FILE_KINDS, limit))


async def expired_messages(before: str, limit: int = 200) -> list[aiosqlite.Row]:
    """Tozalash uchun: guruhlardagi, qadalmagan va saqlanmagan eski xabarlar."""
    return await fetch_all(
        """SELECT s.chat_id, s.message_id, s.kind FROM sent_messages s
           JOIN chats c ON c.chat_id = s.chat_id
           WHERE s.sent_at < ? AND s.pinned = 0 AND s.keep = 0
             AND c.type IN ('group','supergroup')
           ORDER BY s.sent_at LIMIT ?""", (before, limit))


async def sent_summary() -> dict:
    total = await fetch_one("SELECT COUNT(*) AS n FROM sent_messages")
    pinned = await fetch_one("SELECT COUNT(*) AS n FROM sent_messages WHERE pinned=1")
    marks = ",".join("?" * len(FILE_KINDS))
    files = await fetch_one(
        f"SELECT COUNT(*) AS n FROM sent_messages WHERE kind IN ({marks})", FILE_KINDS)
    return {"total": total["n"], "pinned": pinned["n"], "files": files["n"]}


# ------------------------------------------------------ global sozlamalar
async def get_setting(key: str, default: str = "") -> str:
    row = await fetch_one("SELECT value FROM bot_settings WHERE key=?", (key,))
    return row["value"] if row else default


async def set_setting(key: str, value) -> None:
    await execute(
        """INSERT INTO bot_settings(key, value) VALUES(?,?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
        (key, str(value)))


def iso_ago(days: float = 0, hours: float = 0) -> str:
    """created_at bilan solishtirish uchun bir xil formatdagi ISO vaqt.

    Diqqat: SQLite'ning datetime('now') bo'sh joyli format beradi va bizdagi
    «T» li ISO satr bilan to'g'ri solishtirilmaydi — shuning uchun Python'da
    aynan bir xil ko'rinishda yasaymiz.
    """
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(days=days, hours=hours)) \
        .isoformat(timespec="seconds")


async def activity_stats() -> dict:
    """Bot faoliyati bo'yicha umumiy ko'rsatkichlar."""
    day, week, month = iso_ago(1), iso_ago(7), iso_ago(30)

    users = await fetch_one(
        """SELECT COUNT(*) AS total,
                  COALESCE(SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END), 0) AS new_day,
                  COALESCE(SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END), 0) AS new_week,
                  COALESCE(SUM(CASE WHEN last_seen  >= ? THEN 1 ELSE 0 END), 0) AS live_week,
                  COALESCE(SUM(CASE WHEN last_seen  >= ? THEN 1 ELSE 0 END), 0) AS live_month,
                  COALESCE(SUM(COALESCE(blocked, 0)), 0) AS blocked
           FROM users""", (day, week, week, month))

    sessions = await fetch_one(
        """SELECT COUNT(*) AS total,
                  COALESCE(SUM(CASE WHEN started_at >= ? THEN 1 ELSE 0 END), 0) AS today,
                  COALESCE(SUM(CASE WHEN status='active' THEN 1 ELSE 0 END), 0) AS active
           FROM sessions""", (day,))

    by_mode = {r["mode"]: r["n"] for r in await fetch_all(
        "SELECT mode, COUNT(*) AS n FROM sessions GROUP BY mode")}

    answers = await fetch_one(
        """SELECT COUNT(*) AS total,
                  COALESCE(SUM(is_correct), 0) AS correct,
                  COALESCE(SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END), 0) AS today
           FROM answers""", (day,))

    chats = await fetch_one(
        "SELECT COUNT(*) AS n FROM chats WHERE type IN ('group','supergroup')")
    cols = await fetch_one("SELECT COUNT(*) AS n FROM collections")
    questions = await fetch_one("SELECT COUNT(*) AS n FROM questions")

    return {"users": dict(users), "sessions": dict(sessions), "by_mode": by_mode,
            "answers": dict(answers), "chats": chats["n"],
            "collections": cols["n"], "questions": questions["n"]}


async def group_activity() -> list[aiosqlite.Row]:
    """Guruhlar kesimida faollik."""
    return await fetch_all(
        """SELECT c.chat_id, c.title, c.last_seen,
                  (SELECT COUNT(*) FROM chat_members m WHERE m.chat_id = c.chat_id) AS members,
                  (SELECT COUNT(*) FROM sessions s WHERE s.chat_id = c.chat_id) AS games,
                  (SELECT COUNT(*) FROM answers a
                     JOIN sessions s2 ON s2.id = a.session_id
                    WHERE s2.chat_id = c.chat_id) AS answers,
                  (SELECT MAX(s3.started_at) FROM sessions s3
                    WHERE s3.chat_id = c.chat_id) AS last_game,
                  (SELECT COUNT(*) FROM collection_shares cs
                    WHERE cs.chat_id = c.chat_id) AS shared
           FROM chats c
           WHERE c.type IN ('group','supergroup')
           ORDER BY games DESC, c.last_seen DESC""")


async def collection_activity() -> list[aiosqlite.Row]:
    return await fetch_all(
        """SELECT c.id, c.title, c.kind, c.visibility, c.owner_id,
                  u.full_name AS owner_name,
                  (SELECT COUNT(*) FROM questions q WHERE q.collection_id = c.id) AS n,
                  (SELECT COUNT(*) FROM sessions s WHERE s.collection_id = c.id) AS games
           FROM collections c LEFT JOIN users u ON u.user_id = c.owner_id
           ORDER BY games DESC, c.id""")


async def first_user_id() -> int | None:
    row = await fetch_one("SELECT user_id FROM users ORDER BY created_at LIMIT 1")
    return row["user_id"] if row else None


async def get_prefs(user_id: int) -> dict:
    row = await fetch_one("SELECT * FROM prefs WHERE user_id=?", (user_id,))
    if row is None:
        default_col = await default_collection_id()
        await execute(
            "INSERT INTO prefs(user_id, collection_id, count, timer) VALUES(?,?,?,?)",
            (user_id, default_col, config.DEFAULT_COUNT, config.DEFAULT_TIMER),
        )
        row = await fetch_one("SELECT * FROM prefs WHERE user_id=?", (user_id,))
    data = dict(row)
    if not data.get("collection_id"):
        data["collection_id"] = await default_collection_id()
    return data


async def set_pref(user_id: int, field: str, value: Any) -> None:
    if field not in {
        "collection_id", "count", "timer", "shuffle_q",
        "shuffle_a", "instant", "skip_learned",
    }:
        raise ValueError(field)
    await get_prefs(user_id)
    await execute(f"UPDATE prefs SET {field}=? WHERE user_id=?", (value, user_id))


# ---------------------------------------------------------------- collections
async def default_collection_id() -> int | None:
    row = await fetch_one("SELECT id FROM collections WHERE is_default=1 ORDER BY id LIMIT 1")
    if row:
        return row["id"]
    row = await fetch_one("SELECT id FROM collections ORDER BY id LIMIT 1")
    return row["id"] if row else None


async def create_collection(title: str, owner_id: int | None, description: str = "",
                            is_default: int = 0, visibility: str = "private",
                            kind: str = "quiz") -> int:
    return await execute(
        "INSERT INTO collections(title, description, owner_id, is_default,"
        " visibility, kind, created_at) VALUES(?,?,?,?,?,?,?)",
        (title.strip()[:120], description[:400], owner_id, is_default,
         visibility, kind, now()),
    )


async def collection(col_id: int) -> aiosqlite.Row | None:
    return await fetch_one("SELECT * FROM collections WHERE id=?", (col_id,))


async def list_collections() -> list[aiosqlite.Row]:
    return await fetch_all(
        """SELECT c.*, (SELECT COUNT(*) FROM questions q WHERE q.collection_id=c.id) AS n
           FROM collections c ORDER BY c.is_default DESC, c.id"""
    )


# ------------------------------------------------------- ruxsatlar / ko'rinish
VISIBILITY = ("private", "groups", "public")


async def set_visibility(col_id: int, visibility: str) -> None:
    if visibility not in VISIBILITY:
        raise ValueError(visibility)
    await execute("UPDATE collections SET visibility=? WHERE id=?", (visibility, col_id))


async def share_chats(col_id: int) -> list[int]:
    rows = await fetch_all(
        "SELECT chat_id FROM collection_shares WHERE collection_id=?", (col_id,))
    return [r["chat_id"] for r in rows]


async def toggle_share(col_id: int, chat_id: int) -> bool:
    row = await fetch_one(
        "SELECT 1 FROM collection_shares WHERE collection_id=? AND chat_id=?",
        (col_id, chat_id))
    if row:
        await execute(
            "DELETE FROM collection_shares WHERE collection_id=? AND chat_id=?",
            (col_id, chat_id))
        return False
    await execute(
        "INSERT INTO collection_shares(collection_id, chat_id, created_at) VALUES(?,?,?)",
        (col_id, chat_id, now()))
    return True


async def shared_collections_for_chat(chat_id: int) -> list[int]:
    rows = await fetch_all(
        "SELECT collection_id FROM collection_shares WHERE chat_id=?", (chat_id,))
    return [r["collection_id"] for r in rows]


async def touch_chat(chat_id: int, title: str, kind: str,
                     username: str | None = None) -> None:
    await execute(
        """INSERT INTO chats(chat_id, title, type, username, added_at, last_seen)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(chat_id) DO UPDATE SET
             title=excluded.title, type=excluded.type,
             username=COALESCE(NULLIF(excluded.username, ''), chats.username),
             last_seen=excluded.last_seen""",
        (chat_id, title or "", kind, username or "", now(), now()))


async def set_chat_link(chat_id: int, invite_link: str) -> None:
    await execute("UPDATE chats SET invite_link=? WHERE chat_id=?",
                  (invite_link or "", chat_id))


async def touch_group(chat_id: int, title: str, kind: str, user_id: int | None) -> None:
    """Guruh va a'zoni bitta tranzaksiyada belgilash (middleware uchun)."""
    conn = await connect()
    ts = now()
    await conn.execute(
        """INSERT INTO chats(chat_id, title, type, added_at, last_seen) VALUES(?,?,?,?,?)
           ON CONFLICT(chat_id) DO UPDATE SET
             title=excluded.title, type=excluded.type, last_seen=excluded.last_seen""",
        (chat_id, title or "", kind, ts, ts))
    if user_id is not None:
        await conn.execute(
            """INSERT INTO chat_members(chat_id, user_id, last_seen) VALUES(?,?,?)
               ON CONFLICT(chat_id, user_id) DO UPDATE SET last_seen=excluded.last_seen""",
            (chat_id, user_id, ts))
    await conn.commit()


async def touch_chat_member(chat_id: int, user_id: int) -> None:
    await execute(
        """INSERT INTO chat_members(chat_id, user_id, last_seen) VALUES(?,?,?)
           ON CONFLICT(chat_id, user_id) DO UPDATE SET last_seen=excluded.last_seen""",
        (chat_id, user_id, now()))


async def user_chats(user_id: int) -> list[aiosqlite.Row]:
    """Foydalanuvchi bot bilan ishlatgan guruhlar."""
    return await fetch_all(
        """SELECT c.chat_id, c.title, c.type FROM chats c
           JOIN chat_members m ON m.chat_id = c.chat_id
           WHERE m.user_id = ? AND c.type IN ('group','supergroup')
           ORDER BY m.last_seen DESC""", (user_id,))


async def chat(chat_id: int) -> aiosqlite.Row | None:
    return await fetch_one("SELECT * FROM chats WHERE chat_id=?", (chat_id,))


async def owned_collections(user_id: int, kind: str = 'quiz') -> list[aiosqlite.Row]:
    return await fetch_all(
        """SELECT c.*, (SELECT COUNT(*) FROM questions q WHERE q.collection_id=c.id) AS n
           FROM collections c WHERE c.owner_id=? AND COALESCE(c.kind,'quiz')=? ORDER BY c.id""", (user_id, kind))


async def candidate_collections(user_id: int, kind: str = "quiz") -> list[aiosqlite.Row]:
    """O'zi egasi, ochiq, yoki guruhga ulashilgan bazalar (a'zolik keyin tekshiriladi)."""
    return await fetch_all(
        """SELECT c.*, (SELECT COUNT(*) FROM questions q WHERE q.collection_id=c.id) AS n
           FROM collections c
           WHERE COALESCE(c.kind,'quiz') = ?
             AND (c.owner_id = ?
                  OR c.visibility = 'public'
                  OR (c.visibility = 'groups' AND EXISTS (
                        SELECT 1 FROM collection_shares s WHERE s.collection_id = c.id)))
           ORDER BY (c.owner_id = ?) DESC, c.is_default DESC, c.id""",
        (kind, user_id, user_id))


async def collections_for_chat(chat_id: int, kind: str = "quiz") -> list[aiosqlite.Row]:
    """Guruhda o'ynash mumkin bo'lgan bazalar: ochiq yoki shu guruhga ulashilgan."""
    return await fetch_all(
        """SELECT c.*, (SELECT COUNT(*) FROM questions q WHERE q.collection_id=c.id) AS n
           FROM collections c
           WHERE COALESCE(c.kind,'quiz') = ?
             AND (c.visibility = 'public'
                  OR EXISTS (SELECT 1 FROM collection_shares s
                             WHERE s.collection_id = c.id AND s.chat_id = ?))
           ORDER BY c.is_default DESC, c.id""", (kind, chat_id))


async def delete_collection(col_id: int) -> bool:
    """Default baza hech qachon o'chirilmaydi (savollari ham)."""
    col = await collection(col_id)
    if not col or col["is_default"]:
        return False
    await execute("DELETE FROM questions WHERE collection_id=?", (col_id,))
    await execute("DELETE FROM collection_shares WHERE collection_id=?", (col_id,))
    await execute("DELETE FROM collections WHERE id=?", (col_id,))
    return True


# ---------------------------------------------------------------- questions
async def add_questions(col_id: int, items: Sequence[dict]) -> tuple[int, int]:
    """items: [{text, options, correct, explanation}] -> (qo'shildi, takror)."""
    conn = await connect()
    added = dup = 0
    for it in items:
        opts = [str(o).strip() for o in it["options"]]
        image = (it.get("image") or "")[:512]
        opt_images = [str(x) for x in (it.get("option_images") or [])]
        fp = fingerprint(it["text"], opts, image, opt_images)
        try:
            await conn.execute(
                """INSERT INTO questions(collection_id, text, options, correct,
                                         explanation, difficulty, category, image,
                                         option_images, fingerprint, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (col_id, it["text"].strip(), json.dumps(opts, ensure_ascii=False),
                 int(it["correct"]), (it.get("explanation") or "").strip(),
                 int(it.get("difficulty") or 2), (it.get("category") or "")[:60],
                 image, json.dumps(opt_images) if opt_images else "", fp, now()),
            )
            added += 1
        except aiosqlite.IntegrityError:
            dup += 1
    await conn.commit()
    return added, dup


async def count_questions(col_id: int) -> int:
    row = await fetch_one("SELECT COUNT(*) AS n FROM questions WHERE collection_id=?", (col_id,))
    return row["n"] if row else 0


async def question(q_id: int) -> dict | None:
    row = await fetch_one("SELECT * FROM questions WHERE id=?", (q_id,))
    return _q_to_dict(row) if row else None


async def questions_by_ids(ids: Sequence[int]) -> dict[int, dict]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = await fetch_all(f"SELECT * FROM questions WHERE id IN ({marks})", ids)
    return {r["id"]: _q_to_dict(r) for r in rows}


def _q_to_dict(row: aiosqlite.Row) -> dict:
    keys = row.keys()
    return {
        "id": row["id"],
        "collection_id": row["collection_id"],
        "text": row["text"],
        "options": json.loads(row["options"]),
        "correct": row["correct"],
        "explanation": row["explanation"] or "",
        "difficulty": (row["difficulty"] if "difficulty" in keys else 2) or 2,
        "category": (row["category"] if "category" in keys else "") or "",
        "image": (row["image"] if "image" in keys else "") or "",
        "option_images": json.loads(row["option_images"])
        if "option_images" in keys and row["option_images"] else [],
    }


def make_perm(q: dict, shuffle: bool = True) -> list[int]:
    """Variantlar tartibi. Variantlari rasm bo'lgan savolda tartib o'zgarmaydi —
    harflar rasmdagi yozuvlarga mos kelishi kerak."""
    order = list(range(len(q["options"])))
    if shuffle and not q.get("option_images"):
        random.shuffle(order)
    return order


async def pick_questions(col_id: int, limit: int, user_id: int | None = None,
                         skip_learned: bool = False, shuffle: bool = True) -> list[int]:
    sql = "SELECT id FROM questions WHERE collection_id=?"
    params: list[Any] = [col_id]
    if skip_learned and user_id:
        sql += " AND id NOT IN (SELECT question_id FROM learned WHERE user_id=?)"
        params.append(user_id)
    sql += " ORDER BY id"
    ids = [r["id"] for r in await fetch_all(sql, params)]
    if shuffle:
        random.shuffle(ids)
    return ids[:limit] if limit > 0 else ids


# ---------------------------------------------------------------- learned
async def toggle_learned(user_id: int, q_id: int) -> bool:
    row = await fetch_one(
        "SELECT 1 FROM learned WHERE user_id=? AND question_id=?", (user_id, q_id))
    if row:
        await execute("DELETE FROM learned WHERE user_id=? AND question_id=?", (user_id, q_id))
        return False
    await execute(
        "INSERT INTO learned(user_id, question_id, created_at) VALUES(?,?,?)",
        (user_id, q_id, now()))
    return True


async def is_learned(user_id: int, q_id: int) -> bool:
    return await fetch_one(
        "SELECT 1 FROM learned WHERE user_id=? AND question_id=?", (user_id, q_id)) is not None


async def learned_count(user_id: int, col_id: int) -> int:
    row = await fetch_one(
        """SELECT COUNT(*) AS n FROM learned l JOIN questions q ON q.id=l.question_id
           WHERE l.user_id=? AND q.collection_id=?""", (user_id, col_id))
    return row["n"] if row else 0


# ---------------------------------------------------------------- sessions
async def create_session(owner_id: int, chat_id: int, col_id: int, mode: str,
                         q_ids: Sequence[int], settings: dict) -> int:
    return await execute(
        """INSERT INTO sessions(owner_id, chat_id, collection_id, mode, q_ids,
                                cursor, status, settings, started_at)
           VALUES(?,?,?,?,?,0,'active',?,?)""",
        (owner_id, chat_id, col_id, mode, json.dumps(list(q_ids)),
         json.dumps(settings, ensure_ascii=False), now()),
    )


async def get_session(sid: int) -> dict | None:
    row = await fetch_one("SELECT * FROM sessions WHERE id=?", (sid,))
    if not row:
        return None
    data = dict(row)
    data["q_ids"] = json.loads(data["q_ids"])
    data["settings"] = json.loads(data["settings"] or "{}")
    return data


async def set_cursor(sid: int, cursor: int) -> None:
    await execute("UPDATE sessions SET cursor=? WHERE id=?", (cursor, sid))


async def finish_session(sid: int, status: str = "done") -> None:
    await execute("UPDATE sessions SET status=?, finished_at=? WHERE id=?", (status, now(), sid))


async def active_session(owner_id: int, mode: str | None = None) -> dict | None:
    """Foydalanuvchining shaxsiy chatdagi faol testi (guruh o'yinlari kirmaydi)."""
    sql = "SELECT id FROM sessions WHERE owner_id=? AND chat_id=owner_id AND status='active'"
    params: list[Any] = [owner_id]
    if mode:
        sql += " AND mode=?"
        params.append(mode)
    sql += " ORDER BY id DESC LIMIT 1"
    row = await fetch_one(sql, params)
    return await get_session(row["id"]) if row else None


async def private_active_ids(owner_id: int) -> list[int]:
    rows = await fetch_all(
        "SELECT id FROM sessions WHERE owner_id=? AND chat_id=owner_id AND status='active'",
        (owner_id,))
    return [r["id"] for r in rows]


async def abort_active(owner_id: int) -> None:
    """Faqat shaxsiy chatdagi testlarni yopadi — foydalanuvchi tashkil qilgan
    guruh o'yiniga tegmaydi (guruh sessiyasida chat_id — guruh id'si)."""
    await execute(
        """UPDATE sessions SET status='aborted', finished_at=?
           WHERE owner_id=? AND chat_id=owner_id AND status='active'""",
        (now(), owner_id))


# ---------------------------------------------------------------- answers
async def save_answer(session_id: int, user_id: int, user_name: str, q_index: int,
                      question_id: int, chosen: int, is_correct: bool,
                      spent_ms: int = 0) -> bool:
    conn = await connect()
    try:
        await conn.execute(
            """INSERT INTO answers(session_id, user_id, user_name, question_id, q_index,
                                   chosen, is_correct, spent_ms, created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (session_id, user_id, user_name, question_id, q_index, chosen,
             int(is_correct), spent_ms, now()),
        )
        await conn.commit()
        return True
    except aiosqlite.IntegrityError:
        await conn.execute(
            """UPDATE answers SET chosen=?, is_correct=?, spent_ms=?, created_at=?
               WHERE session_id=? AND user_id=? AND q_index=?""",
            (chosen, int(is_correct), spent_ms, now(), session_id, user_id, q_index))
        await conn.commit()
        return False


async def session_answers(sid: int, user_id: int | None = None) -> list[aiosqlite.Row]:
    if user_id is None:
        return await fetch_all(
            "SELECT * FROM answers WHERE session_id=? ORDER BY q_index", (sid,))
    return await fetch_all(
        "SELECT * FROM answers WHERE session_id=? AND user_id=? ORDER BY q_index",
        (sid, user_id))


async def leaderboard(sid: int) -> list[aiosqlite.Row]:
    return await fetch_all(
        """SELECT user_id, user_name,
                  SUM(is_correct) AS correct,
                  COUNT(*) AS total,
                  SUM(spent_ms) AS ms
           FROM answers WHERE session_id=?
           GROUP BY user_id ORDER BY correct DESC, ms ASC""", (sid,))


async def user_stats(user_id: int) -> dict:
    row = await fetch_one(
        """SELECT COUNT(*) AS total, COALESCE(SUM(is_correct),0) AS correct
           FROM answers WHERE user_id=?""", (user_id,))
    sess = await fetch_one(
        """SELECT COUNT(*) AS n FROM sessions
           WHERE owner_id=? AND status='done'""", (user_id,))
    learned = await fetch_one(
        "SELECT COUNT(*) AS n FROM learned WHERE user_id=?", (user_id,))
    return {
        "answers": row["total"] if row else 0,
        "correct": row["correct"] if row else 0,
        "sessions": sess["n"] if sess else 0,
        "learned": learned["n"] if learned else 0,
    }


async def weak_questions(user_id: int, limit: int = 30) -> list[int]:
    rows = await fetch_all(
        """SELECT question_id, SUM(CASE WHEN is_correct=0 THEN 1 ELSE 0 END) AS bad
           FROM answers WHERE user_id=?
             AND session_id NOT IN (SELECT id FROM sessions WHERE mode='iq')
           GROUP BY question_id
           HAVING bad > 0 ORDER BY bad DESC, MAX(created_at) DESC LIMIT ?""",
        (user_id, limit))
    return [r["question_id"] for r in rows]


async def chat_leaderboard(chat_id: int, limit: int = 15) -> list[aiosqlite.Row]:
    return await fetch_all(
        """SELECT a.user_id, COALESCE(u.full_name, a.user_name) AS name,
                  COUNT(*) AS total, SUM(a.is_correct) AS correct,
                  COUNT(DISTINCT a.session_id) AS games
           FROM answers a
           JOIN sessions s ON s.id = a.session_id
           LEFT JOIN users u ON u.user_id = a.user_id
           WHERE s.chat_id = ?
           GROUP BY a.user_id
           ORDER BY correct DESC, total ASC LIMIT ?""",
        (chat_id, limit))


async def global_top(limit: int = 15) -> list[aiosqlite.Row]:
    return await fetch_all(
        """SELECT a.user_id, COALESCE(u.full_name, a.user_name) AS name,
                  COUNT(*) AS total, SUM(a.is_correct) AS correct
           FROM answers a LEFT JOIN users u ON u.user_id=a.user_id
           GROUP BY a.user_id HAVING total >= 10
           ORDER BY (SUM(a.is_correct)*1.0/COUNT(*)) DESC, total DESC LIMIT ?""",
        (limit,))


# ---------------------------------------------------------------- media keshi
async def media_get(key: str) -> str | None:
    row = await fetch_one("SELECT file_id FROM media_cache WHERE key=?", (key,))
    return row["file_id"] if row else None


async def media_put(key: str, file_id: str) -> None:
    await execute(
        """INSERT INTO media_cache(key, file_id, created_at) VALUES(?,?,?)
           ON CONFLICT(key) DO UPDATE SET file_id=excluded.file_id""",
        (key, file_id, now()))
