"""Administrator: ommaviy xabar yuborish (broadcast)."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from aiogram import Bot, F, Router, types
from aiogram.exceptions import (TelegramAPIError, TelegramBadRequest,
                                TelegramForbiddenError, TelegramRetryAfter)
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import bg
import config
import db
import recorder
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


# ---------------------------------------------------------------- /faoliyat
MODE_ICON = {"classic": "🎯 Klassik", "pro": "🧠 Pro", "iq": "🧩 IQ",
             "battle": "⚔️ Pro jang"}


def _ago(iso: str | None) -> str:
    if not iso:
        return "hech qachon"
    from datetime import datetime, timezone
    delta = (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds()
    if delta < 3600:
        return f"{int(delta // 60)} daq oldin"
    if delta < 86400:
        return f"{int(delta // 3600)} soat oldin"
    return f"{int(delta // 86400)} kun oldin"


async def _overview() -> str:
    st = await db.activity_stats()
    u, s, a = st["users"], st["sessions"], st["answers"]
    acc = (a["correct"] / a["total"] * 100) if a["total"] else 0
    modes = " · ".join(
        f"{MODE_ICON.get(m, m)} {n}" for m, n in sorted(
            st["by_mode"].items(), key=lambda x: -x[1])) or "—"
    return (
        "📊 <b>Bot faoliyati</b>\n\n"
        "<b>👤 Foydalanuvchilar</b>\n"
        f"Jami: <b>{u['total']}</b>\n"
        f"Yangi: bugun {u['new_day']} · haftada {u['new_week']}\n"
        f"Faol: haftada <b>{u['live_week']}</b> · oyda {u['live_month']}\n"
        + (f"Bloklaganlar: {u['blocked']}\n" if u["blocked"] else "")
        + "\n<b>🧩 Testlar</b>\n"
        f"Jami sessiya: <b>{s['total']}</b>  (bugun {s['today']}"
        + (f", hozir faol {s['active']}" if s["active"] else "") + ")\n"
        f"Rejimlar: {modes}\n"
        f"Javoblar: <b>{a['total']}</b> (bugun {a['today']})\n"
        f"Umumiy aniqlik: <b>{acc:.0f}%</b>\n"
        "\n<b>📚 Kontent</b>\n"
        f"Bazalar: <b>{st['collections']}</b> · savollar: <b>{st['questions']}</b>\n"
        f"Guruhlar: <b>{st['chats']}</b>")


async def _groups_text() -> str:
    rows = await db.group_activity()
    if not rows:
        return ("👥 <b>Guruhlar</b>\n\n<i>Bot hali birorta guruhga qo'shilmagan.</i>")
    lines = [f"👥 <b>Guruhlar</b> — {len(rows)} ta\n"]
    for r in rows:
        lines.append(
            f"• <b>{ui.esc(r['title'] or r['chat_id'])}</b>\n"
            f"   👤 {r['members']} a'zo · 🧩 {r['games']} o'yin · "
            f"✍️ {r['answers']} javob\n"
            f"   📚 ochilgan baza: {r['shared']} · oxirgi o'yin: {_ago(r['last_game'])}")
    return "\n".join(lines)


async def _collections_text() -> str:
    rows = await db.collection_activity()
    icon = {"private": "🔒", "groups": "👥", "public": "🌍"}
    lines = [f"📚 <b>Bazalar</b> — {len(rows)} ta\n"]
    for r in rows:
        kind = " 🧩" if r["kind"] == "iq" else ""
        lines.append(
            f"• <b>{ui.esc(r['title'])}</b>{kind}\n"
            f"   {icon.get(r['visibility'], '?')} {r['n']} ta savol · "
            f"{r['games']} marta ishlatilgan\n"
            f"   👤 {ui.esc(r['owner_name'] or 'bot')}")
    return "\n".join(lines)


async def _top_text() -> str:
    rows = await db.global_top(15)
    if not rows:
        return "🏆 <b>Top foydalanuvchilar</b>\n\n<i>Hali ma'lumot yo'q.</i>"
    lines = ["🏆 <b>Eng faol foydalanuvchilar</b> (≥10 javob)\n"]
    for i, r in enumerate(rows, 1):
        acc = r["correct"] / r["total"] * 100 if r["total"] else 0
        lines.append(f"{ui.medal(i)} {ui.esc(r['name'] or 'Foydalanuvchi')} — "
                     f"{r['total']} javob, {acc:.0f}% aniqlik")
    return "\n".join(lines)


SECTIONS = {"main": _overview, "grp": _groups_text,
            "col": _collections_text, "top": _top_text}


def _act_kb(active: str) -> types.InlineKeyboardMarkup:
    tabs = [("📊 Umumiy", "main"), ("👥 Guruhlar", "grp"),
            ("📚 Bazalar", "col"), ("🏆 Top", "top")]
    row = [((("• " + t) if key == active else t), f"act:{key}") for t, key in tabs]
    return ui.kb([row[:2], row[2:], [("🔄 Yangilash", f"act:{active}")]])


@router.message(Command("faoliyat", "stat", "activity"))
async def cmd_activity(message: types.Message) -> None:
    if not await is_admin(message.from_user.id):
        return
    if message.chat.type != "private":
        await message.answer("Bu buyruq faqat bot bilan yakka chatda ishlaydi.")
        return
    await message.answer(await _overview(), reply_markup=_act_kb("main"))


@router.callback_query(F.data.startswith("act:"))
async def cb_activity(call: types.CallbackQuery) -> None:
    if not await is_admin(call.from_user.id):
        await call.answer("Bu bo'lim faqat admin uchun.", show_alert=True)
        return
    key = call.data.split(":")[1]
    builder = SECTIONS.get(key)
    if builder is None:
        await call.answer()
        return
    text = await builder()
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text[:4000], reply_markup=_act_kb(key))
    await call.answer()


# ---------------------------------------------------------------- /tozalash
HOUR_CHOICES = [1, 3, 6, 12, 24, 48]


async def _clean_panel() -> tuple[str, types.InlineKeyboardMarkup]:
    on = (await db.get_setting(recorder.KEY_ENABLED, "1")) == "1"
    hours = int(float(await db.get_setting(recorder.KEY_HOURS,
                                           str(recorder.DEFAULT_HOURS))))
    st = await db.sent_summary()
    pending = len(await db.expired_messages(db.iso_ago(hours=hours), 1000))

    holat = "yoniq ✅" if on else "o'chiq ❌"
    text = (
        "🧹 <b>Avtomatik tozalash</b>\n\n"
        f"Holat: <b>{holat}</b>\n"
        f"Muddat: <b>{hours} soat</b>\n\n"
        "Bot guruhlarga yuborgan xabarlar (test savollari, natijalar, "
        "e'lonlar) shu muddatdan keyin o'chiriladi.\n\n"
        f"📊 Hisobga olingan: <b>{st['total']}</b> ta xabar\n"
        f"📌 Qadalganlar: <b>{st['pinned']}</b> — <i>ular hech qachon o'chmaydi</i>\n"
        f"📎 Fayllar: <b>{st['files']}</b>\n"
        f"⏳ Navbatda: <b>{pending}</b> ta o'chirishga tayyor\n\n"
        "<i>⚠️ Telegram botga 48 soatdan eski xabarni o'chirishga ruxsat "
        "bermasligi mumkin — bunday xabarlar ro'yxatdan shunchaki chiqariladi.</i>"
    )
    rows = [[("🔴 O'chirish" if on else "🟢 Yoqish", "cl:toggle")]]
    cur = []
    for h in HOUR_CHOICES:
        cur.append((f"{'• ' if h == hours else ''}{h} soat", f"cl:h:{h}"))
        if len(cur) == 3:
            rows.append(cur)
            cur = []
    if cur:
        rows.append(cur)
    rows.append([("🧹 Hozir tozalash", "cl:now"), ("🔄 Yangilash", "cl:show")])
    return text, ui.kb(rows)


@router.message(Command("tozalash", "clean"))
async def cmd_clean(message: types.Message) -> None:
    if not await is_admin(message.from_user.id):
        return
    if message.chat.type != "private":
        await message.answer("Bu buyruq faqat bot bilan yakka chatda ishlaydi.")
        return
    text, kb = await _clean_panel()
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("cl:"))
async def cb_clean(call: types.CallbackQuery) -> None:
    if not await is_admin(call.from_user.id):
        await call.answer("Bu bo'lim faqat admin uchun.", show_alert=True)
        return
    parts = call.data.split(":")
    action = parts[1]

    if action == "toggle":
        on = (await db.get_setting(recorder.KEY_ENABLED, "1")) == "1"
        await db.set_setting(recorder.KEY_ENABLED, "0" if on else "1")
        await call.answer("Tozalash o'chirildi" if on else "Tozalash yoqildi")
    elif action == "h":
        await db.set_setting(recorder.KEY_HOURS, parts[2])
        await call.answer(f"Muddat: {parts[2]} soat")
    elif action == "now":
        await call.answer("Tozalanmoqda…")
        done, failed = await recorder.clean_once(call.bot)
        with contextlib.suppress(TelegramBadRequest):
            await call.message.answer(
                f"🧹 Tozalandi: <b>{done}</b> ta o'chirildi"
                + (f", {failed} tasiga ruxsat yetmadi" if failed else ""))
    else:
        await call.answer()

    text, kb = await _clean_panel()
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=kb)


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

    await state.update_data(pin=False)
    count = await _count(target)
    await message.answer(_confirm_text(target, count), reply_markup=_confirm_kb(False))


def _confirm_text(target: dict, count: int) -> str:
    return (f"👆 Yuqoridagi xabar <b>{ui.esc(target['label'])}</b> ga yuboriladi.\n"
            f"📊 Qabul qiluvchilar soni: <b>{count}</b>\n"
            f"⏱ Taxminiy vaqt: ~{max(1, round(count * SEND_DELAY))} soniya\n\n"
            "Tasdiqlaysizmi?")


def _confirm_kb(pin: bool) -> types.InlineKeyboardMarkup:
    return ui.kb([
        [("📌 Qadab qo'yish: " + ("HA ✅" if pin else "yo'q"), "ad:pin")],
        [("✅ Yuborish", "ad:go"), ("❌ Bekor", "ad:cancel")],
    ])


@router.callback_query(F.data == "ad:pin")
async def cb_pin_toggle(call: types.CallbackQuery, state: FSMContext) -> None:
    if not await is_admin(call.from_user.id):
        await call.answer()
        return
    data = await state.get_data()
    pin = not data.get("pin", False)
    await state.update_data(pin=pin)
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_reply_markup(reply_markup=_confirm_kb(pin))
    await call.answer("📌 Qadaladi" if pin else "Qadalmaydi")


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
    pin = bool(data.get("pin"))
    await state.clear()
    if not target or not src_msg:
        await call.answer("Xabar topilmadi, /xabar dan qayta boshlang.", show_alert=True)
        return
    await call.answer("Yuborish boshlandi")
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text("📤 Yuborilmoqda…")
    bg.spawn(_run_cast(call.bot, call.message.chat.id, call.message.message_id,
                       target, src_chat, src_msg, pin))


async def _run_cast(bot: Bot, report_chat: int, report_msg: int, target: dict,
                    src_chat: int, src_msg: int, pin: bool = False) -> None:
    targets = await _recipients(target)
    sent = failed = blocked = pinned = 0
    started = time.monotonic()

    async def progress(final: bool = False) -> None:
        elapsed = time.monotonic() - started
        text = (("✅ <b>Yuborish tugadi</b>\n\n" if final else "📤 <b>Yuborilmoqda…</b>\n\n")
                + f"🎯 Qabul qiluvchi: <b>{ui.esc(target['label'])}</b>\n"
                + f"{ui.progress_bar(sent + failed + blocked, len(targets), 12)} "
                + f"{sent + failed + blocked}/{len(targets)}\n\n"
                + f"✅ Yetkazildi: <b>{sent}</b>\n"
                + (f"📌 Qadaldi: <b>{pinned}</b>\n" if pin else "")
                + (f"🚫 Bloklagan: <b>{blocked}</b>\n" if blocked else "")
                + (f"⚠️ Xato: <b>{failed}</b>\n" if failed else "")
                + f"⏱ {ui.fmt_time(elapsed)}")
        with contextlib.suppress(Exception):
            await bot.edit_message_text(text, chat_id=report_chat, message_id=report_msg)

    for i, chat_id in enumerate(targets, 1):
        try:
            copied = await bot.copy_message(chat_id=chat_id, from_chat_id=src_chat,
                                            message_id=src_msg)
            sent += 1
            if pin and await _pin(bot, chat_id, copied.message_id):
                pinned += 1
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
    log.info("Broadcast tugadi: %s ✅ / %s 📌 / %s 🚫 / %s ⚠️",
             sent, pinned, blocked, failed)


async def _pin(bot: Bot, chat_id: int, message_id: int) -> bool:
    """Xabarni qadaydi. Bot admin bo'lmasa yoki huquqi yetmasa — jim o'tadi."""
    try:
        await bot.pin_chat_message(chat_id=chat_id, message_id=message_id,
                                   disable_notification=True)
        await db.mark_pinned(chat_id, message_id)
        return True
    except TelegramRetryAfter as exc:
        await asyncio.sleep(exc.retry_after + 1)
        with contextlib.suppress(TelegramAPIError):
            await bot.pin_chat_message(chat_id=chat_id, message_id=message_id,
                                       disable_notification=True)
            await db.mark_pinned(chat_id, message_id)
            return True
        return False
    except TelegramAPIError as exc:
        log.info("qadab bo'lmadi (%s): %s", chat_id, exc)
        return False
