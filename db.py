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
"""

_conn: aiosqlite.Connection | None = None


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fingerprint(text: str, options: Sequence[str]) -> str:
    raw = text.strip().lower() + "||" + "|".join(sorted(o.strip().lower() for o in options))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


async def connect() -> aiosqlite.Connection:
    global _conn
    if _conn is None:
        _conn = await aiosqlite.connect(config.DB_PATH)
        _conn.row_factory = aiosqlite.Row
        await _conn.executescript(SCHEMA)
        await _conn.commit()
    return _conn


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
                            is_default: int = 0) -> int:
    return await execute(
        "INSERT INTO collections(title, description, owner_id, is_default, created_at)"
        " VALUES(?,?,?,?,?)",
        (title.strip()[:120], description[:400], owner_id, is_default, now()),
    )


async def collection(col_id: int) -> aiosqlite.Row | None:
    return await fetch_one("SELECT * FROM collections WHERE id=?", (col_id,))


async def list_collections() -> list[aiosqlite.Row]:
    return await fetch_all(
        """SELECT c.*, (SELECT COUNT(*) FROM questions q WHERE q.collection_id=c.id) AS n
           FROM collections c ORDER BY c.is_default DESC, c.id"""
    )


async def delete_collection(col_id: int) -> None:
    await execute("DELETE FROM questions WHERE collection_id=?", (col_id,))
    await execute("DELETE FROM collections WHERE id=? AND is_default=0", (col_id,))


# ---------------------------------------------------------------- questions
async def add_questions(col_id: int, items: Sequence[dict]) -> tuple[int, int]:
    """items: [{text, options, correct, explanation}] -> (qo'shildi, takror)."""
    conn = await connect()
    added = dup = 0
    for it in items:
        opts = [str(o).strip() for o in it["options"]]
        fp = fingerprint(it["text"], opts)
        try:
            await conn.execute(
                """INSERT INTO questions(collection_id, text, options, correct,
                                         explanation, fingerprint, created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (col_id, it["text"].strip(), json.dumps(opts, ensure_ascii=False),
                 int(it["correct"]), (it.get("explanation") or "").strip(), fp, now()),
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
    return {
        "id": row["id"],
        "collection_id": row["collection_id"],
        "text": row["text"],
        "options": json.loads(row["options"]),
        "correct": row["correct"],
        "explanation": row["explanation"] or "",
    }


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
    sql = "SELECT id FROM sessions WHERE owner_id=? AND status='active'"
    params: list[Any] = [owner_id]
    if mode:
        sql += " AND mode=?"
        params.append(mode)
    sql += " ORDER BY id DESC LIMIT 1"
    row = await fetch_one(sql, params)
    return await get_session(row["id"]) if row else None


async def abort_active(owner_id: int) -> None:
    await execute(
        "UPDATE sessions SET status='aborted', finished_at=? WHERE owner_id=? AND status='active'",
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
           FROM answers WHERE user_id=? GROUP BY question_id
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
