"""Test boshlashdan oldingi sozlama kartasi (ikkala rejim uchun umumiy)."""
from __future__ import annotations

from aiogram import F, Router, types
from aiogram.enums import ChatType
from aiogram.filters import Command

import config
import db
import ui

router = Router(name="setup")

MODE_TITLE = {
    "classic": "🎯 <b>Klassik rejim</b> — QuizBot uslubi",
    "pro": "🧠 <b>Pro rejim</b> — zamonaviy interfeys",
}


async def setup_card(user_id: int, mode: str) -> tuple[str, types.InlineKeyboardMarkup]:
    prefs = await db.get_prefs(user_id)
    col_id = prefs["collection_id"]
    col = await db.collection(col_id) if col_id else None
    total = await db.count_questions(col_id) if col_id else 0
    learned = await db.learned_count(user_id, col_id) if col_id else 0

    if not col:
        return ("📚 Hozircha birorta baza yo'q. «➕ Savol qo'shish» orqali fayl yuklang.",
                ui.kb([[("📚 Bazalar", "lib:list")]]))

    count = prefs["count"]
    count_label = "barchasi" if count <= 0 or count >= total else str(count)
    lines = [
        MODE_TITLE[mode], "",
        f"📚 Baza: <b>{ui.esc(col['title'])}</b> — {total} ta savol",
        f"🔢 Savollar soni: <b>{count_label}</b>",
    ]
    if mode == "classic":
        lines.append(f"⏱ Har savolga: <b>{prefs['timer']} soniya</b>")
    lines += [
        f"🔀 Savollar aralash: <b>{_yn(prefs['shuffle_q'])}</b>   "
        f"Variantlar aralash: <b>{_yn(prefs['shuffle_a'])}</b>",
    ]
    if mode == "pro":
        lines.append(f"⚡ Darhol javobni ko'rsatish: <b>{_yn(prefs['instant'])}</b>")
    if learned:
        lines.append(
            f"🎓 O'rganilganlarni tashlab ketish: <b>{_yn(prefs['skip_learned'])}</b>"
            f" ({learned} ta belgilangan)")

    rows: list[list[tuple[str, str]]] = [
        [("📚 Bazani almashtirish", f"su:{mode}:col")],
        [("🔢 Savollar soni", f"su:{mode}:count")],
    ]
    if mode == "classic":
        rows.append([("⏱ Vaqt", f"su:{mode}:timer")])
    rows.append([
        (f"🔀 Savollar {_mark(prefs['shuffle_q'])}", f"su:{mode}:t:shuffle_q"),
        (f"🔀 Variantlar {_mark(prefs['shuffle_a'])}", f"su:{mode}:t:shuffle_a"),
    ])
    if mode == "pro":
        rows.append([(f"⚡ Darhol javob {_mark(prefs['instant'])}", f"su:{mode}:t:instant")])
    if learned:
        rows.append([(f"🎓 O'rganilganlarsiz {_mark(prefs['skip_learned'])}",
                      f"su:{mode}:t:skip_learned")])
    rows.append([("▶️ Testni boshlash", f"su:{mode}:go")])
    if mode == "pro":
        rows.append([("🔁 Xatolar ustida ishlash", "su:pro:mistakes")])
    return "\n".join(lines), ui.kb(rows)


def _yn(v) -> str:
    return "ha" if v else "yo'q"


def _mark(v) -> str:
    return "✅" if v else "❌"


@router.message(Command("quiz"), F.chat.type == ChatType.PRIVATE)
@router.message(F.text == ui.BTN_CLASSIC)
async def open_classic(message: types.Message) -> None:
    await db.touch_user(message.from_user.id, message.from_user.full_name,
                        message.from_user.username)
    text, markup = await setup_card(message.from_user.id, "classic")
    await message.answer(text, reply_markup=markup)


@router.message(Command("pro"), F.chat.type == ChatType.PRIVATE)
@router.message(F.text == ui.BTN_PRO)
async def open_pro(message: types.Message) -> None:
    await db.touch_user(message.from_user.id, message.from_user.full_name,
                        message.from_user.username)
    text, markup = await setup_card(message.from_user.id, "pro")
    await message.answer(text, reply_markup=markup)


@router.message(Command("sozlamalar"))
@router.message(F.text == ui.BTN_SETTINGS)
async def open_settings(message: types.Message) -> None:
    text, markup = await setup_card(message.from_user.id, "pro")
    await message.answer(
        "⚙️ <b>Sozlamalar</b> — ikkala rejimga ham tegishli.\n\n" + text,
        reply_markup=markup)


@router.callback_query(F.data.startswith("su:"))
async def on_setup(call: types.CallbackQuery) -> None:
    _, mode, action, *rest = call.data.split(":")
    uid = call.from_user.id

    if action == "back":
        await _refresh(call, mode)
        return

    if action == "t":
        field = rest[0]
        prefs = await db.get_prefs(uid)
        await db.set_pref(uid, field, 0 if prefs[field] else 1)
        await _refresh(call, mode)
        return

    if action == "col":
        cols = await db.list_collections()
        rows = [[(f"{'⭐️ ' if c['is_default'] else ''}{ui.shorten(c['title'], 28)} "
                  f"· {c['n']}", f"su:{mode}:setcol:{c['id']}")] for c in cols]
        rows.append([("⬅️ Orqaga", f"su:{mode}:back")])
        await call.message.edit_text("📚 Bazani tanlang:", reply_markup=ui.kb(rows))
        await call.answer()
        return

    if action == "setcol":
        await db.set_pref(uid, "collection_id", int(rest[0]))
        await _refresh(call, mode)
        await call.answer("Baza tanlandi ✅")
        return

    if action == "count":
        prefs = await db.get_prefs(uid)
        total = await db.count_questions(prefs["collection_id"])
        choices = [c for c in config.COUNT_CHOICES if c < total]
        rows, cur = [], []
        for c in choices:
            cur.append((str(c), f"su:{mode}:setcount:{c}"))
            if len(cur) == 3:
                rows.append(cur)
                cur = []
        if cur:
            rows.append(cur)
        rows.append([(f"Barchasi ({total})", f"su:{mode}:setcount:0")])
        rows.append([("⬅️ Orqaga", f"su:{mode}:back")])
        await call.message.edit_text("🔢 Nechta savol bo'lsin?", reply_markup=ui.kb(rows))
        await call.answer()
        return

    if action == "setcount":
        await db.set_pref(uid, "count", int(rest[0]))
        await _refresh(call, mode)
        await call.answer("Saqlandi ✅")
        return

    if action == "timer":
        rows, cur = [], []
        for t in config.TIMER_CHOICES:
            cur.append((f"{t} s", f"su:{mode}:settimer:{t}"))
            if len(cur) == 3:
                rows.append(cur)
                cur = []
        if cur:
            rows.append(cur)
        rows.append([("⬅️ Orqaga", f"su:{mode}:back")])
        await call.message.edit_text("⏱ Har bir savolga qancha vaqt?",
                                     reply_markup=ui.kb(rows))
        await call.answer()
        return

    if action == "settimer":
        await db.set_pref(uid, "timer", int(rest[0]))
        await _refresh(call, mode)
        await call.answer("Saqlandi ✅")
        return

    if action == "go":
        from handlers import classic, pro
        await call.answer()
        if mode == "classic":
            await classic.start_quiz(call.message, call.from_user)
        else:
            await pro.start_quiz(call.message, call.from_user)
        return

    if action == "mistakes":
        from handlers import pro
        await call.answer()
        await pro.start_quiz(call.message, call.from_user, only_mistakes=True)
        return


async def _refresh(call: types.CallbackQuery, mode: str) -> None:
    text, markup = await setup_card(call.from_user.id, mode)
    try:
        await call.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass
    await call.answer()
