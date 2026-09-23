"""Bazalar (savollar to'plami), import/eksport."""
from __future__ import annotations

import contextlib

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import db
import importers
import ui

router = Router(name="library")

MAX_FILE = 20 * 1024 * 1024


class Lib(StatesGroup):
    new_title = State()
    wait_file = State()
    wait_text = State()


# --------------------------------------------------------------- bazalar ro'yxati
async def _list_text_kb(user_id: int):
    cols = await db.list_collections()
    prefs = await db.get_prefs(user_id)
    lines = ["📚 <b>Bazalar</b>\n"]
    rows = []
    for c in cols:
        active = " ⭐️" if c["id"] == prefs["collection_id"] else ""
        lines.append(f"• <b>{ui.esc(c['title'])}</b> — {c['n']} ta savol{active}")
        rows.append([(f"{ui.shorten(c['title'], 26)} · {c['n']}", f"lib:open:{c['id']}")])
    if not cols:
        lines.append("<i>Hozircha baza yo'q.</i>")
    lines.append("\n⭐️ — hozir tanlangan baza")
    rows.append([("➕ Yangi baza", "lib:new"), ("⬆️ Fayl yuklash", "lib:import")])
    return "\n".join(lines), ui.kb(rows)


@router.message(Command("bazalar"))
@router.message(F.text == ui.BTN_LIB)
async def show_library(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _list_text_kb(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "lib:list")
async def cb_list(call: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _list_text_kb(call.from_user.id)
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=markup)
    with contextlib.suppress(TelegramBadRequest):
        await call.answer()


@router.callback_query(F.data.startswith("lib:open:"))
async def cb_open(call: types.CallbackQuery) -> None:
    await _render_collection(call, int(call.data.split(":")[2]))
    with contextlib.suppress(TelegramBadRequest):
        await call.answer()


async def _render_collection(call: types.CallbackQuery, col_id: int) -> None:
    col = await db.collection(col_id)
    if not col:
        await call.answer("Baza topilmadi.", show_alert=True)
        return
    n = await db.count_questions(col_id)
    learned = await db.learned_count(call.from_user.id, col_id)
    text = (f"📚 <b>{ui.esc(col['title'])}</b>\n"
            f"{ui.esc(col['description'] or '')}\n\n"
            f"🔢 Savollar: <b>{n}</b>\n"
            f"🎓 «O'rgandim» belgilangan: <b>{learned}</b>")
    rows = [
        [("⭐️ Shu bazani tanlash", f"lib:pick:{col_id}")],
        [("🎯 Klassik test", f"lib:run:{col_id}:classic"),
         ("🧠 Pro test", f"lib:run:{col_id}:pro")],
        [("⬆️ Savol qo'shish", f"lib:addto:{col_id}"),
         ("⬇️ JSON eksport", f"lib:export:{col_id}")],
    ]
    if not col["is_default"]:
        rows.append([("🗑 Bazani o'chirish", f"lib:del:{col_id}")])
    rows.append([("⬅️ Ro'yxat", "lib:list")])
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=ui.kb(rows))


@router.callback_query(F.data.startswith("lib:pick:"))
async def cb_pick(call: types.CallbackQuery) -> None:
    col_id = int(call.data.split(":")[2])
    await db.set_pref(call.from_user.id, "collection_id", col_id)
    await _render_collection(call, col_id)
    with contextlib.suppress(TelegramBadRequest):
        await call.answer("⭐️ Bu baza tanlandi")


@router.callback_query(F.data.startswith("lib:run:"))
async def cb_run(call: types.CallbackQuery) -> None:
    _, _, col_id, mode = call.data.split(":")
    await db.set_pref(call.from_user.id, "collection_id", int(col_id))
    from handlers import classic, pro
    await call.answer()
    if mode == "classic":
        await classic.start_quiz(call.message, call.from_user)
    else:
        await pro.start_quiz(call.message, call.from_user)


@router.callback_query(F.data.startswith("lib:del:"))
async def cb_del(call: types.CallbackQuery) -> None:
    col_id = int(call.data.split(":")[2])
    await call.message.edit_text(
        "🗑 Bu bazani va undagi barcha savollarni o'chirishni tasdiqlaysizmi?",
        reply_markup=ui.kb([[("✅ Ha, o'chir", f"lib:del2:{col_id}"),
                             ("❌ Yo'q", f"lib:open:{col_id}")]]))
    await call.answer()


@router.callback_query(F.data.startswith("lib:del2:"))
async def cb_del2(call: types.CallbackQuery, state: FSMContext) -> None:
    col_id = int(call.data.split(":")[2])
    await db.delete_collection(col_id)
    prefs = await db.get_prefs(call.from_user.id)
    if prefs["collection_id"] == col_id:
        await db.set_pref(call.from_user.id, "collection_id", await db.default_collection_id())
    await call.answer("O'chirildi")
    await cb_list(call, state)


@router.callback_query(F.data.startswith("lib:export:"))
async def cb_export(call: types.CallbackQuery) -> None:
    col_id = int(call.data.split(":")[2])
    col = await db.collection(col_id)
    ids = await db.pick_questions(col_id, 0, shuffle=False)
    qs = await db.questions_by_ids(ids)
    payload = importers.to_json_export(col["title"], [qs[i] for i in ids if i in qs])
    file = types.BufferedInputFile(
        payload.encode("utf-8"),
        filename=f"{col['title'][:40].replace(' ', '_')}.json")
    await call.message.answer_document(
        file, caption=f"⬇️ <b>{ui.esc(col['title'])}</b> — {len(ids)} ta savol")
    await call.answer()


# ------------------------------------------------------------------- yangi baza
@router.callback_query(F.data == "lib:new")
async def cb_new(call: types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Lib.new_title)
    await call.message.answer("📝 Yangi baza nomini yuboring:\n<i>(bekor qilish: /start)</i>")
    await call.answer()


@router.message(Lib.new_title, F.text)
async def on_new_title(message: types.Message, state: FSMContext) -> None:
    title = message.text.strip()
    if len(title) < 2:
        await message.answer("Nom juda qisqa. Qaytadan yuboring.")
        return
    col_id = await db.create_collection(title, message.from_user.id)
    await db.set_pref(message.from_user.id, "collection_id", col_id)
    await state.set_state(Lib.wait_file)
    await state.update_data(col_id=col_id)
    await message.answer(
        f"✅ <b>{ui.esc(title)}</b> bazasi yaratildi va tanlandi.\n\n"
        + _upload_hint(), reply_markup=ui.main_menu())


# ------------------------------------------------------------------- import
def _upload_hint() -> str:
    return (
        "⬆️ Endi savollar faylini yuboring:\n\n"
        "• <b>.json</b> — <code>[{\"question\":\"…\",\"options\":[…],\"answer\":0}]</code> "
        "yoki <code>[{\"q\":\"…\",\"c\":\"to'g'ri\",\"a\":[\"xato\",…]}]</code>\n"
        "• <b>.docx</b> — Word fayl. To'g'ri javob <code>+</code> bilan belgilansa "
        "yoki <code>Javob: B</code> satri bo'lsa aniq o'qiydi.\n"
        "• <b>.txt</b> — xuddi shu ko'rinishdagi oddiy matn\n\n"
        "Yoki savollarni shu yerga <b>matn ko'rinishida</b> yozib yuboring:\n"
        "<pre>1. Poytaxt qaysi shahar?\n+Toshkent\n-Samarqand\n-Buxoro</pre>"
    )


@router.message(Command("qoshish"))
@router.message(F.text == ui.BTN_ADD)
async def cmd_add(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    cols = await db.list_collections()
    prefs = await db.get_prefs(message.from_user.id)
    rows = [[(f"{'⭐️ ' if c['id'] == prefs['collection_id'] else ''}"
              f"{ui.shorten(c['title'], 26)} · {c['n']}", f"lib:addto:{c['id']}")]
            for c in cols]
    rows.append([("➕ Yangi baza ochish", "lib:new")])
    await message.answer("➕ Savollar qaysi bazaga qo'shilsin?", reply_markup=ui.kb(rows))


@router.callback_query(F.data == "lib:import")
async def cb_import(call: types.CallbackQuery, state: FSMContext) -> None:
    prefs = await db.get_prefs(call.from_user.id)
    await _arm_upload(call.message, state, prefs["collection_id"])
    await call.answer()


@router.callback_query(F.data.startswith("lib:addto:"))
async def cb_addto(call: types.CallbackQuery, state: FSMContext) -> None:
    col_id = int(call.data.split(":")[2])
    await _arm_upload(call.message, state, col_id)
    await call.answer()


async def _arm_upload(message: types.Message, state: FSMContext, col_id: int) -> None:
    col = await db.collection(col_id)
    if not col:
        await message.answer("Baza topilmadi.")
        return
    await state.set_state(Lib.wait_file)
    await state.update_data(col_id=col_id)
    await message.answer(
        f"📚 Baza: <b>{ui.esc(col['title'])}</b>\n\n" + _upload_hint())


@router.message(StateFilter(Lib.wait_file), F.document)
@router.message(F.document)
async def on_document(message: types.Message, state: FSMContext) -> None:
    doc = message.document
    name = (doc.file_name or "").lower()
    if not name.endswith((".json", ".docx", ".doc", ".txt", ".md")):
        return
    if doc.file_size and doc.file_size > MAX_FILE:
        await message.answer("❌ Fayl juda katta (20 MB dan oshmasin).")
        return

    data = await state.get_data()
    col_id = data.get("col_id") or (await db.get_prefs(message.from_user.id))["collection_id"]
    if not col_id:
        col_id = await db.create_collection("Mening bazam", message.from_user.id)
        await db.set_pref(message.from_user.id, "collection_id", col_id)

    status = await message.answer("⏳ Fayl o'qilmoqda…")
    try:
        buf = await message.bot.download(doc)
        result = importers.parse_file(doc.file_name or "", buf.read())
    except importers.ImportError_ as exc:
        await status.edit_text(f"❌ {ui.esc(exc)}")
        return
    except Exception as exc:  # pragma: no cover
        await status.edit_text(f"❌ Faylni o'qib bo'lmadi: <code>{ui.esc(exc)}</code>")
        return

    await _preview(status, state, result, col_id, source=doc.file_name)


@router.message(StateFilter(Lib.wait_file), F.text, ~F.text.startswith("/"))
async def on_text_block(message: types.Message, state: FSMContext) -> None:
    if message.text in {ui.BTN_CLASSIC, ui.BTN_PRO, ui.BTN_LIB, ui.BTN_ADD,
                        ui.BTN_STATS, ui.BTN_SETTINGS, ui.BTN_HELP}:
        await state.clear()
        return
    data = await state.get_data()
    col_id = data.get("col_id") or (await db.get_prefs(message.from_user.id))["collection_id"]
    try:
        result = importers.parse_txt(message.text.encode("utf-8"))
    except importers.ImportError_ as exc:
        await message.answer(f"❌ {ui.esc(exc)}")
        return
    status = await message.answer("⏳ Tahlil qilinmoqda…")
    await _preview(status, state, result, col_id, source="matn")


async def _preview(status: types.Message, state: FSMContext,
                   result: importers.ImportResult, col_id: int, source: str) -> None:
    col = await db.collection(col_id)
    await state.update_data(pending=result.questions, col_id=col_id)
    lines = [
        f"🔎 <b>Tahlil natijasi</b> — <code>{ui.esc(source)}</code>\n",
        f"✅ Topildi: <b>{result.count}</b> ta savol",
    ]
    if result.skipped:
        lines.append(f"⏭ O'tkazib yuborildi: {result.skipped} ta (noto'liq blok)")
    for note in result.notes:
        lines.append(note)
    lines.append(f"\n📚 Qo'shiladigan baza: <b>{ui.esc(col['title'])}</b>")
    lines.append("\n<b>Namuna:</b>")
    for q in result.questions[:2]:
        lines.append(f"\n<b>{ui.esc(ui.shorten(q['text'], 150))}</b>")
        lines.append(ui.render_options(q["options"], correct=q["correct"], reveal=True))
    body = "\n".join(lines)
    await status.edit_text(
        body[:4000],
        reply_markup=ui.kb([[("✅ Bazaga saqlash", "lib:save"),
                             ("❌ Bekor qilish", "lib:cancel")]]))


@router.callback_query(F.data == "lib:save")
async def cb_save(call: types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    pending = data.get("pending")
    col_id = data.get("col_id")
    if not pending or not col_id:
        await call.answer("Saqlanadigan ma'lumot topilmadi.", show_alert=True)
        return
    added, dup = await db.add_questions(col_id, pending)
    total = await db.count_questions(col_id)
    col = await db.collection(col_id)
    await state.clear()
    await call.message.edit_text(
        f"✅ <b>Saqlandi!</b>\n\n"
        f"➕ Yangi qo'shildi: <b>{added}</b>\n"
        + (f"♻️ Takrorlangani o'tkazib yuborildi: {dup}\n" if dup else "")
        + f"📚 <b>{ui.esc(col['title'])}</b> bazasida endi <b>{total}</b> ta savol bor.",
        reply_markup=ui.kb([
            [("🎯 Klassik test", f"lib:run:{col_id}:classic"),
             ("🧠 Pro test", f"lib:run:{col_id}:pro")],
            [("📚 Bazalar", "lib:list")],
        ]))
    await call.answer()


@router.callback_query(F.data == "lib:cancel")
async def cb_cancel(call: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text("❌ Bekor qilindi.")
    await call.answer()
