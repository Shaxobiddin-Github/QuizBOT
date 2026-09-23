"""Bazalarga kirish huquqi: guruh a'zoligi, ko'rinish filtri, chat kuzatuvi."""
from __future__ import annotations

import contextlib
import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.types import TelegramObject, Update

import db

log = logging.getLogger("access")

MEMBER_TTL = 1800          # a'zolik javobini 30 daqiqa keshlaymiz
_member_cache: dict[tuple[int, int], tuple[bool, float]] = {}
ACTIVE_STATUSES = {"creator", "administrator", "member", "restricted"}

VIS_LABEL = {
    "private": "🔒 Faqat men",
    "groups": "👥 Tanlangan guruhlar",
    "public": "🌍 Hamma",
}


async def is_member(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Foydalanuvchi shu guruh a'zosimi? (keshlangan)"""
    key = (chat_id, user_id)
    hit = _member_cache.get(key)
    now = time.monotonic()
    if hit and now - hit[1] < MEMBER_TTL:
        return hit[0]
    result = None
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        result = member.status in ACTIVE_STATUSES
    except Exception as exc:
        log.debug("get_chat_member(%s,%s) xato: %s", chat_id, user_id, exc)
        # API javob bermasa — botda ko'rilgan a'zolikka tayanamiz
        row = await db.fetch_one(
            "SELECT 1 FROM chat_members WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        result = row is not None
    _member_cache[key] = (result, now)
    return result


def forget_membership(chat_id: int, user_id: int) -> None:
    _member_cache.pop((chat_id, user_id), None)


async def visible_collections(bot: Bot, user_id: int) -> list:
    """Foydalanuvchi ko'ra oladigan bazalar."""
    out = []
    for col in await db.candidate_collections(user_id):
        if col["owner_id"] == user_id or col["visibility"] == "public":
            out.append(col)
            continue
        if col["visibility"] == "groups":
            for chat_id in await db.share_chats(col["id"]):
                if await is_member(bot, chat_id, user_id):
                    out.append(col)
                    break
    return out


async def can_access(bot: Bot, user_id: int, col_id: int) -> bool:
    col = await db.collection(col_id)
    if not col:
        return False
    if col["owner_id"] == user_id or col["visibility"] == "public":
        return True
    if col["visibility"] == "groups":
        for chat_id in await db.share_chats(col["id"]):
            if await is_member(bot, chat_id, user_id):
                return True
    return False


async def ensure_collection(bot: Bot, user_id: int) -> int | None:
    """Foydalanuvchining tanlangan bazasi hali ham ochiqmi; bo'lmasa boshqasini beradi."""
    prefs = await db.get_prefs(user_id)
    col_id = prefs["collection_id"]
    if col_id and await can_access(bot, user_id, col_id):
        return col_id
    cols = await visible_collections(bot, user_id)
    cols = [c for c in cols if c["n"]] or cols
    new_id = cols[0]["id"] if cols else None
    await db.set_pref(user_id, "collection_id", new_id)
    return new_id


async def shareable_chats(user_id: int) -> list:
    """Bazani ulashish mumkin bo'lgan guruhlar — bot va foydalanuvchi birga bo'lganlari."""
    return await db.user_chats(user_id)


async def share_label(col) -> str:
    """Baza ko'rinishining qisqa tavsifi."""
    vis = col["visibility"] if "visibility" in col.keys() else "public"
    if vis != "groups":
        return VIS_LABEL.get(vis, vis)
    chat_ids = await db.share_chats(col["id"])
    if not chat_ids:
        return "👥 guruh tanlanmagan"
    titles = []
    for cid in chat_ids[:2]:
        row = await db.chat(cid)
        titles.append(row["title"] if row and row["title"] else str(cid))
    more = f" +{len(chat_ids) - 2}" if len(chat_ids) > 2 else ""
    return "👥 " + ", ".join(titles) + more


class ChatTracker(BaseMiddleware):
    """Har bir yangilanishda guruh va undagi foydalanuvchini bazaga belgilab boradi."""

    async def __call__(self, handler: Callable[[TelegramObject, dict], Awaitable[Any]],
                       event: TelegramObject, data: dict) -> Any:
        with contextlib.suppress(Exception):
            await self._track(event)
        return await handler(event, data)

    @staticmethod
    async def _track(update: Update) -> None:
        chat = user = None
        for field in ("message", "edited_message", "callback_query",
                      "my_chat_member", "chat_member"):
            obj = getattr(update, field, None)
            if obj is None:
                continue
            user = getattr(obj, "from_user", None)
            chat = getattr(obj, "chat", None)
            if chat is None and getattr(obj, "message", None) is not None:
                chat = obj.message.chat
            break
        if chat is None or chat.type not in ("group", "supergroup"):
            return
        await db.touch_chat(chat.id, chat.title or "", chat.type)
        if user is not None and not user.is_bot:
            await db.touch_chat_member(chat.id, user.id)
            _member_cache[(chat.id, user.id)] = (True, time.monotonic())
