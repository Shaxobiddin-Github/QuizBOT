"""Bot yuborgan xabarlarni ro'yxatga olish va eskilarini avtomatik tozalash.

Telegram Bot API botga chat tarixini qidirishga ruxsat bermaydi — shuning uchun
«bot fayllari» va «eski xabarlarni o'chirish» faqat biz o'zimiz yozib borgan
xabarlar ustida ishlaydi (ya'ni shu funksiya qo'shilgandan keyingilari).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.methods import (CopyMessage, ForwardMessage, SendAnimation, SendAudio,
                             SendDocument, SendMessage, SendPhoto, SendPoll,
                             SendVideo, SendVoice)
from aiogram.types import Message, MessageId

import db

log = logging.getLogger("recorder")

# Avtomatik tozalash sozlamalari
KEY_ENABLED = "autoclean_enabled"
KEY_HOURS = "autoclean_hours"
DEFAULT_HOURS = 6
SWEEP_EVERY = 300           # har 5 daqiqada bir tekshiramiz
BATCH = 80                  # bir aylanishda ko'pi bilan shuncha xabar o'chiriladi

KIND_BY_METHOD = {
    SendMessage: "text",
    SendPoll: "poll",
    SendDocument: "document",
    SendPhoto: "photo",
    SendVideo: "video",
    SendAudio: "audio",
    SendVoice: "voice",
    SendAnimation: "animation",
}


def _file_info(message: Message) -> tuple[str, str]:
    """Xabardagi faylning file_id va nomi."""
    if message.document:
        return message.document.file_id, message.document.file_name or "hujjat"
    if message.video:
        return message.video.file_id, message.video.file_name or "video.mp4"
    if message.audio:
        return message.audio.file_id, message.audio.file_name or "audio"
    if message.animation:
        return message.animation.file_id, message.animation.file_name or "animatsiya"
    if message.voice:
        return message.voice.file_id, "ovozli xabar"
    if message.photo:
        return message.photo[-1].file_id, "rasm.jpg"
    return "", ""


class SentRecorder:
    """Bot yuborgan har bir xabarni bazaga yozib boradi."""

    async def __call__(self, make_request, bot: Bot, method):
        result = await make_request(bot, method)
        with contextlib.suppress(Exception):
            await self._record(method, result)
        return result

    @staticmethod
    async def _record(method, result) -> None:
        # Faqat guruhlarni yozamiz: shaxsiy chat id'lari musbat bo'ladi, guruhniki
        # manfiy. Tozalash ham, /fayllar ham faqat guruhlarga tegishli.
        kind = KIND_BY_METHOD.get(type(method))
        if kind and isinstance(result, Message):
            if result.chat.id > 0:
                return
            file_id, file_name = _file_info(result)
            await db.record_sent(result.chat.id, result.message_id, kind, file_id,
                                 file_name, result.caption or result.text or "")
            return
        # copyMessage/forwardMessage faqat message_id qaytaradi — chat_id metoddan
        if isinstance(method, (CopyMessage, ForwardMessage)) and \
                isinstance(result, (MessageId, Message)) and \
                isinstance(method.chat_id, int) and method.chat_id < 0:
            await db.record_sent(method.chat_id, result.message_id, "copy",
                                 caption=getattr(method, "caption", "") or "")


# ------------------------------------------------------------- tozalash
async def clean_once(bot: Bot) -> tuple[int, int]:
    """Muddati o'tgan xabarlarni o'chiradi → (o'chirildi, o'chmadi)."""
    if (await db.get_setting(KEY_ENABLED, "1")) != "1":
        return 0, 0
    hours = float(await db.get_setting(KEY_HOURS, str(DEFAULT_HOURS)))
    rows = await db.expired_messages(db.iso_ago(hours=hours), BATCH)
    done = failed = 0
    for r in rows:
        try:
            await bot.delete_message(r["chat_id"], r["message_id"])
            done += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)
            continue                       # keyingi aylanishda qayta uriladi
        except TelegramAPIError:
            # 48 soatdan eski, allaqachon o'chirilgan yoki huquq yo'q —
            # qayta urinib o'tirmaymiz, yozuvni tashlab yuboramiz
            failed += 1
        await db.forget_message(r["chat_id"], r["message_id"])
        await asyncio.sleep(0.05)          # flood controlga urilmaslik uchun
    if done or failed:
        log.info("Tozalash: %s o'chirildi, %s o'chmadi", done, failed)
    return done, failed


async def sweeper(bot: Bot) -> None:
    """Fonda aylanib turuvchi tozalagich."""
    while True:
        try:
            await asyncio.sleep(SWEEP_EVERY)
            await clean_once(bot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:            # pragma: no cover
            log.error("tozalagich xatosi: %r", exc)
