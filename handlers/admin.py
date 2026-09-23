"""Administrator: ommaviy xabar yuborish (broadcast)."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from aiogram import Bot, F, Router, types
from aiogram.exceptions import (TelegramForbiddenError, TelegramRetryAfter,
                                TelegramBadRequest)
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import bg
import config
import db
import ui

router = Router(name="admin")
log = logging.getLogger("broadcast")

SEND_DELAY = 0.06          # ~16 xabar/sekund — Telegram limitidan pastda
PROGRESS_EVERY = 25


class Cast(StatesGroup):
    wait_message = State()
    confirm = State()


async def is_admin(user_id: int) -> bool:
    """config.ADMINS bo'sh bo'lsa — birinchi ro'yxatdan o'tgan foydalanuvchi."""
    if config.ADMINS:
        return user_id in config.ADMINS
    first = await db.first_user_id()
    return first is not None and first == user_id


# ----------------------------------------------------------------------- /id
@router.message(Command("id"))
async def cmd_id(message: types.Message) -> None:
    admin = "ha" if await is_admin(message.from_user.id) else "yo'q"
    await message.answer(
        f"🆔 Sizning ID: <code>{message.from_user.id}</code>\n"
        f"💬 Chat ID: <code>{message.chat.id}</code>\n"
        f"🛡 Admin: <b>{admin}</b>")


# ------------------------------------------------------------------- /xabar
@router.message(Command("xabar", "broadcast"))
async def cmd_broadcast(message: types.Message, state: FSMContext) -> None:
    if not await is_admin(message.from_user.id):
        return
    if message.chat.type != "private":
        await message.answer("Bu buyruq faqat bot bilan yakka chatda ishlaydi.")
        return
    await state.clear()
    await _targets_menu(message)


async def _targets_menu(message: types.Message) -> None:
    users = await db.broadcast_users()
    groups = await db.broadcast_groups()
    rows = [
        [(f"🌍 Barcha foydalanuvchilar ({len(users)})", "ad:t:users")],
        [(f"👥 Barcha guruhlar ({len(groups)})", "ad:t:groups")],
    ]
    if groups:
        rows.append([("📍 Bitta guruhni tanlash", "ad:pick:0")])
    rows.append([("❌ Bekor", "ad:cancel")])
    await message.answer(
        "📣 <b>Ommaviy xabar</b>\n\nXabar kimga borsin?",
        reply_markup=ui.kb(rows))


@router.callback_query(F.data.startswith("ad:pick:"))
async def cb_pick_group(call: types.CallbackQuery) -> None:
    if not await is_admin(call.from_user.id):
        await call.answer()
        return
    page = int(call.data.split(":")[2])
    groups = await db.broadcast_groups()
    per = 8
    chunk = groups[page * per:(page + 1) * per]
    rows = [[(ui.shorten(g["title"] or str(g["chat_id"]), 34),
              f"ad:t:one:{g['chat_id']}")] for g in chunk]
    nav = []
    if page > 0:
        nav.append(("⬅️", f"ad:pick:{page - 1}"))
    if (page + 1) * per < len(groups):
        nav.append(("➡️", f"ad:pick:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([("⬅️ Orqaga", "ad:back")])
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text("📍 Qaysi guruhga yuborilsin?",
                                     reply_markup=ui.kb(rows))
    await call.answer()


@router.callback_query(F.data == "ad:back")
async def cb_back(call: types.CallbackQuery) -> None:
    users = await db.broadcast_users()
    groups = await db.broadcast_groups()
    rows = [
        [(f"🌍 Barcha foydalanuvchilar ({len(users)})", "ad:t:users")],
        [(f"👥 Barcha guruhlar ({len(groups)})", "ad:t:groups")],
    ]
    if groups:
        rows.append([("📍 Bitta guruhni tanlash", "ad:pick:0")])
    rows.append([("❌ Bekor", "ad:cancel")])
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text("📣 <b>Ommaviy xabar</b>\n\nXabar kimga borsin?",
                                     reply_markup=ui.kb(rows))
    await call.answer()


@router.callback_query(F.data.startswith("ad:t:"))
async def cb_target(call: types.CallbackQuery, state: FSMContext) -> None:
    if not await is_admin(call.from_user.id):
        await call.answer("Bu funksiya faqat admin uchun.", show_alert=True)
        return
    parts = call.data.split(":")
    kind = parts[2]
    target = {"kind": kind}
    if kind == "one":
        target["chat_id"] = int(parts[3])
        row = await db.chat(target["chat_id"])
        label = row["title"] if row and row["title"] else str(target["chat_id"])
    elif kind == "users":
        label = f"barcha foydalanuvchilar ({len(await db.broadcast_users())})"
    else:
        label = f"barcha guruhlar ({len(await db.broadcast_groups())})"
    target["label"] = label

    await state.set_state(Cast.wait_message)
    await state.update_data(target=target)
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(
            f"📣 Qabul qiluvchi: <b>{ui.esc(label)}</b>\n\n"
            "Endi yubormoqchi bo'lgan xabarni menga tashlang.\n"
            "<i>Matn, rasm, video, fayl, ovozli xabar — hammasi bo'ladi. "
            "Formatlash va tugmalar ham saqlanadi.</i>\n\n"
            "Bekor qilish: /bekor")
    await call.answer()


@router.message(Command("bekor"))
async def cmd_cancel(message: types.Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        return
    await state.clear()
    await message.answer("❌ Bekor qilindi.", reply_markup=ui.menu_for(message.chat))


@router.callback_query(F.data == "ad:cancel")
async def cb_cancel(call: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text("❌ Bekor qilindi.")
    await call.answer()


@router.message(StateFilter(Cast.wait_message))
async def on_cast_message(message: types.Message, state: FSMContext) -> None:
    if not await is_admin(message.from_user.id):
        await state.clear()
        return
    if message.text and message.text.startswith("/"):
        return
    data = await state.get_data()
    target = data.get("target")
    if not target:
        await state.clear()
        return
    await state.update_data(src_chat=message.chat.id, src_msg=message.message_id)
    await state.set_state(Cast.confirm)

    count = await _count(target)
    await message.answer(
        f"👆 Yuqoridagi xabar <b>{ui.esc(target['label'])}</b> ga yuboriladi.\n"
        f"📊 Qabul qiluvchilar soni: <b>{count}</b>\n"
        f"⏱ Taxminiy vaqt: ~{max(1, round(count * SEND_DELAY))} soniya\n\n"
        "Tasdiqlaysizmi?",
        reply_markup=ui.kb([[("✅ Yuborish", "ad:go"), ("❌ Bekor", "ad:cancel")]]))


async def _count(target: dict) -> int:
    if target["kind"] == "one":
        return 1
    if target["kind"] == "users":
        return len(await db.broadcast_users())
    return len(await db.broadcast_groups())


async def _recipients(target: dict) -> list[int]:
    if target["kind"] == "one":
        return [target["chat_id"]]
    if target["kind"] == "users":
        return await db.broadcast_users()
    return [g["chat_id"] for g in await db.broadcast_groups()]


@router.callback_query(F.data == "ad:go")
async def cb_go(call: types.CallbackQuery, state: FSMContext) -> None:
    if not await is_admin(call.from_user.id):
        await call.answer("Bu funksiya faqat admin uchun.", show_alert=True)
        return
    data = await state.get_data()
    target, src_chat, src_msg = data.get("target"), data.get("src_chat"), data.get("src_msg")
    await state.clear()
    if not target or not src_msg:
        await call.answer("Xabar topilmadi, /xabar dan qayta boshlang.", show_alert=True)
        return
    await call.answer("Yuborish boshlandi")
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text("📤 Yuborilmoqda…")
    bg.spawn(_run_cast(call.bot, call.message.chat.id,
                                  call.message.message_id, target, src_chat, src_msg))


async def _run_cast(bot: Bot, report_chat: int, report_msg: int, target: dict,
                    src_chat: int, src_msg: int) -> None:
    targets = await _recipients(target)
    sent = failed = blocked = 0
    started = time.monotonic()

    async def progress(final: bool = False) -> None:
        elapsed = time.monotonic() - started
        text = (("✅ <b>Yuborish tugadi</b>\n\n" if final else "📤 <b>Yuborilmoqda…</b>\n\n")
                + f"🎯 Qabul qiluvchi: <b>{ui.esc(target['label'])}</b>\n"
                + f"{ui.progress_bar(sent + failed + blocked, len(targets), 12)} "
                + f"{sent + failed + blocked}/{len(targets)}\n\n"
                + f"✅ Yetkazildi: <b>{sent}</b>\n"
                + (f"🚫 Bloklagan: <b>{blocked}</b>\n" if blocked else "")
                + (f"⚠️ Xato: <b>{failed}</b>\n" if failed else "")
                + f"⏱ {ui.fmt_time(elapsed)}")
        with contextlib.suppress(Exception):
            await bot.edit_message_text(text, chat_id=report_chat, message_id=report_msg)

    for i, chat_id in enumerate(targets, 1):
        try:
            await bot.copy_message(chat_id=chat_id, from_chat_id=src_chat,
                                   message_id=src_msg)
            sent += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)
            try:
                await bot.copy_message(chat_id=chat_id, from_chat_id=src_chat,
                                       message_id=src_msg)
                sent += 1
            except Exception:
                failed += 1
        except TelegramForbiddenError:
            blocked += 1
            if target["kind"] == "users":
                await db.set_blocked(chat_id, True)
        except Exception as exc:
            failed += 1
            log.warning("broadcast %s: %s", chat_id, exc)
        if i % PROGRESS_EVERY == 0:
            await progress()
        await asyncio.sleep(SEND_DELAY)

    await progress(final=True)
    log.info("Broadcast tugadi: %s ✅ / %s 🚫 / %s ⚠️", sent, blocked, failed)
