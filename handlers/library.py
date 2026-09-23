"""Bazalar (savollar to'plami), import/eksport."""
from __future__ import annotations

import asyncio
import contextlib

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import access
import db
import importers
import media
import ui

router = Router(name="library")

MAX_FILE = 20 * 1024 * 1024


class Lib(StatesGroup):
    new_title = State()
    wait_file = State()
    wait_text = State()


# --------------------------------------------------------------- bazalar ro'yxati
async def _list_text_kb(bot, user_id: int):
    cols = await access.visible_collections(bot, user_id)
    prefs = await db.get_prefs(user_id)
    mine = [c for c in cols if c["owner_id"] == user_id]
    others = [c for c in cols if c["owner_id"] != user_id]

    lines = ["📚 <b>Bazalar</b>"]
    rows = []

    async def block(title, items):
        if not items:
            return
        lines.append(f"\n<b>{title}</b>")
        for c in items:
            active = " ⭐️" if c["id"] == prefs["collection_id"] else ""
            tag = await access.share_label(c) if c["owner_id"] == user_id else ""
            lines.append(f"• <b>{ui.esc(c['title'])}</b> — {c['n']} ta savol"
                         + (f"  <i>{ui.esc(tag)}</i>" if tag else "") + active)
            rows.append([(f"{ui.shorten(c['title'], 26)} · {c['n']}",
                          f"lib:open:{c['id']}")])

    await block("👤 Mening bazalarim", mine)
    await block("🤝 Menga ochilganlar", others)
    if not cols:
        lines.append("\n<i>Hozircha sizga ochiq baza yo'q. «➕ Yangi baza» bilan "
                     "o'zingiznikini yarating.</i>")
    else:
        lines.append("\n⭐️ — hozir tanlangan baza")
    rows.append([("➕ Yangi baza", "lib:new"), ("⬆️ Fayl yuklash", "lib:import")])
    return "\n".join(lines), ui.kb(rows)


@router.message(Command("bazalar"))
@router.message(F.text == ui.BTN_LIB)
async def show_library(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _list_text_kb(message.bot, message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "lib:list")
async def cb_list(call: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _list_text_kb(call.bot, call.from_user.id)
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
    uid = call.from_user.id
    if not col:
        await call.answer("Baza topilmadi.", show_alert=True)
        return
    if not await access.can_access(call.bot, uid, col_id):
        await call.answer("Bu baza sizga ochiq emas.", show_alert=True)
        return
    is_owner = col["owner_id"] == uid
    n = await db.count_questions(col_id)
    learned = await db.learned_count(uid, col_id)

    owner_line = ""
    if not is_owner:
        owner = await db.fetch_one("SELECT full_name FROM users WHERE user_id=?",
                                   (col["owner_id"],))
        owner_line = f"👤 Muallif: <b>{ui.esc(owner['full_name'] if owner else '—')}</b>\n"

    text = (f"📚 <b>{ui.esc(col['title'])}</b>\n"
            f"{ui.esc(col['description'] or '')}\n\n"
            f"{owner_line}"
            f"🔢 Savollar: <b>{n}</b>\n"
            f"🎓 «O'rgandim» belgilangan: <b>{learned}</b>\n"
            + (f"🔐 Ko'rinish: <b>{ui.esc(await access.share_label(col))}</b>"
               if is_owner else ""))
    rows = [
        [("⭐️ Shu bazani tanlash", f"lib:pick:{col_id}")],
        [("🎯 Klassik test", f"lib:run:{col_id}:classic"),
         ("🧠 Pro test", f"lib:run:{col_id}:pro")],
    ]
    if is_owner:
        rows.append([("⬆️ Savol qo'shish", f"lib:addto:{col_id}"),
                     ("⬇️ JSON eksport", f"lib:export:{col_id}")])
        rows.append([("🔐 Kim ko'ra oladi?", f"lib:perm:{col_id}")])
        if not col["is_default"]:
            rows.append([("🗑 Bazani o'chirish", f"lib:del:{col_id}")])
    else:
        rows.append([("⬇️ JSON eksport", f"lib:export:{col_id}")])
    rows.append([("⬅️ Ro'yxat", "lib:list")])
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=ui.kb(rows))


# --------------------------------------------------------------------- ruxsatlar
async def _perm_panel(call: types.CallbackQuery, col_id: int) -> None:
    col = await db.collection(col_id)
    uid = call.from_user.id
    if not col or col["owner_id"] != uid:
        await call.answer("Ruxsatlarni faqat baza egasi o'zgartiradi.", show_alert=True)
        return
    vis = col["visibility"]
    chats = await access.shareable_chats(uid)
    shared = set(await db.share_chats(col_id))

    lines = [
        f"🔐 <b>{ui.esc(col['title'])}</b> — kim ko'ra oladi?\n",
        f"Hozir: <b>{ui.esc(access.VIS_LABEL.get(vis, vis))}</b>\n",
        "🔒 <i>Faqat men</i> — bazani boshqa hech kim ko'rmaydi.",
        "👥 <i>Tanlangan guruhlar</i> — quyida belgilagan guruhlaringiz "
        "a'zolari ko'radi.",
        "🌍 <i>Hamma</i> — botning barcha foydalanuvchilariga ochiq.",
    ]
    rows = [[
        ("🔒 Faqat men" + (" ✓" if vis == "private" else ""), f"lib:vis:{col_id}:private"),
        ("👥 Guruhlar" + (" ✓" if vis == "groups" else ""), f"lib:vis:{col_id}:groups"),
        ("🌍 Hamma" + (" ✓" if vis == "public" else ""), f"lib:vis:{col_id}:public"),
    ]]

    if vis == "groups":
        if chats:
            lines.append("\n<b>Guruhlaringiz</b> (belgilanganlar ko'radi):")
            for ch in chats:
                mark = "✅" if ch["chat_id"] in shared else "⬜️"
                lines.append(f"{mark} {ui.esc(ch['title'] or ch['chat_id'])}")
                rows.append([(f"{mark} {ui.shorten(ch['title'] or str(ch['chat_id']), 28)}",
                              f"lib:grp:{col_id}:{ch['chat_id']}")])
        else:
            lines.append(
                "\n⚠️ <b>Hali guruh yo'q.</b> Botni guruhga qo'shing va o'sha yerda "
                "<code>/start</code> yozing — guruh shu ro'yxatda paydo bo'ladi.")
    rows.append([("⬅️ Bazaga qaytish", f"lib:open:{col_id}")])
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text("\n".join(lines), reply_markup=ui.kb(rows))


@router.callback_query(F.data.startswith("lib:perm:"))
async def cb_perm(call: types.CallbackQuery) -> None:
    await _perm_panel(call, int(call.data.split(":")[2]))
    with contextlib.suppress(TelegramBadRequest):
        await call.answer()


@router.callback_query(F.data.startswith("lib:vis:"))
async def cb_vis(call: types.CallbackQuery) -> None:
    _, _, col_id, vis = call.data.split(":")
    col_id = int(col_id)
    col = await db.collection(col_id)
    if not col or col["owner_id"] != call.from_user.id:
        await call.answer("Ruxsatlarni faqat baza egasi o'zgartiradi.", show_alert=True)
        return
    await db.set_visibility(col_id, vis)
    await _perm_panel(call, col_id)
    with contextlib.suppress(TelegramBadRequest):
        await call.answer(access.VIS_LABEL.get(vis, vis))


@router.callback_query(F.data.startswith("lib:grp:"))
async def cb_grp(call: types.CallbackQuery) -> None:
    _, _, col_id, chat_id = call.data.split(":")
    col_id, chat_id = int(col_id), int(chat_id)
    col = await db.collection(col_id)
    if not col or col["owner_id"] != call.from_user.id:
        await call.answer("Ruxsatlarni faqat baza egasi o'zgartiradi.", show_alert=True)
        return
    on = await db.toggle_share(col_id, chat_id)
    await _perm_panel(call, col_id)
    with contextlib.suppress(TelegramBadRequest):
        await call.answer("✅ Guruhga ochildi" if on else "⬜️ Guruhdan olib tashlandi")


@router.callback_query(F.data.startswith("lib:pick:"))
async def cb_pick(call: types.CallbackQuery) -> None:
    col_id = int(call.data.split(":")[2])
    if not await access.can_access(call.bot, call.from_user.id, col_id):
        await call.answer("Bu baza sizga ochiq emas.", show_alert=True)
        return
    await db.set_pref(call.from_user.id, "collection_id", col_id)
    await _render_collection(call, col_id)
    with contextlib.suppress(TelegramBadRequest):
        await call.answer("⭐️ Bu baza tanlandi")


@router.callback_query(F.data.startswith("lib:run:"))
async def cb_run(call: types.CallbackQuery) -> None:
    _, _, col_id, mode = call.data.split(":")
    if not await access.can_access(call.bot, call.from_user.id, int(col_id)):
        await call.answer("Bu baza sizga ochiq emas.", show_alert=True)
        return
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
    col = await db.collection(col_id)
    if not col or col["owner_id"] != call.from_user.id:
        await call.answer("O'chirishni faqat baza egasi qila oladi.", show_alert=True)
        return
    if col["is_default"]:
        await call.answer("Asosiy (default) bazani o'chirib bo'lmaydi.", show_alert=True)
        return
    await call.message.edit_text(
        "🗑 Bu bazani va undagi barcha savollarni o'chirishni tasdiqlaysizmi?",
        reply_markup=ui.kb([[("✅ Ha, o'chir", f"lib:del2:{col_id}"),
                             ("❌ Yo'q", f"lib:open:{col_id}")]]))
    await call.answer()


@router.callback_query(F.data.startswith("lib:del2:"))
async def cb_del2(call: types.CallbackQuery, state: FSMContext) -> None:
    col_id = int(call.data.split(":")[2])
    col = await db.collection(col_id)
    if not col or col["owner_id"] != call.from_user.id:
        await call.answer("O'chirishni faqat baza egasi qila oladi.", show_alert=True)
        return
    if not await db.delete_collection(col_id):
        await call.answer("Asosiy (default) bazani o'chirib bo'lmaydi.", show_alert=True)
        return
    prefs = await db.get_prefs(call.from_user.id)
    if prefs["collection_id"] == col_id:
        await db.set_pref(call.from_user.id, "collection_id", await db.default_collection_id())
    await call.answer("O'chirildi")
    await cb_list(call, state)


@router.callback_query(F.data.startswith("lib:export:"))
async def cb_export(call: types.CallbackQuery) -> None:
    col_id = int(call.data.split(":")[2])
    if not await access.can_access(call.bot, call.from_user.id, col_id):
        await call.answer("Bu baza sizga ochiq emas.", show_alert=True)
        return
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
    col_id = await db.create_collection(title, message.from_user.id,
                                        visibility="private")
    await db.set_pref(message.from_user.id, "collection_id", col_id)
    await state.set_state(Lib.wait_file)
    await state.update_data(col_id=col_id)
    await message.answer(
        f"✅ <b>{ui.esc(title)}</b> bazasi yaratildi va tanlandi.\n"
        f"🔒 Hozircha uni <b>faqat siz</b> ko'rasiz — keyin «📚 Bazalar» → "
        f"«🔐 Kim ko'ra oladi?» orqali guruhingizga ochasiz.\n\n"
        + _upload_hint(), reply_markup=ui.menu_for(message.chat))


# ------------------------------------------------------------------- import
def _upload_hint() -> str:
    return (
        "⬆️ Endi savollar faylini yuboring:\n\n"
        "• <b>.json</b> — <code>[{\"question\":\"…\",\"options\":[…],\"answer\":0}]</code> "
        "yoki <code>[{\"q\":\"…\",\"c\":\"to'g'ri\",\"a\":[\"xato\",…]}]</code>\n"
        "• <b>.docx</b> — Word fayl. To'g'ri javob <code>+</code> bilan belgilansa "
        "yoki <code>Javob: B</code> satri bo'lsa aniq o'qiydi.\n"
        "• <b>.txt</b> — xuddi shu ko'rinishdagi oddiy matn\n"
        "• <b>.zip</b> — rasmli savollar: ichida .json va rasmlar, masalan "
        "<code>{\"question\":\"…\",\"image\":\"1.png\",\"option_images\":"
        "[\"a.png\",\"b.png\",\"c.png\"],\"answer\":\"B\"}</code>\n\n"
        "Yoki savollarni shu yerga <b>matn ko'rinishida</b> yozib yuboring:\n"
        "<pre>1. Poytaxt qaysi shahar?\n+Toshkent\n-Samarqand\n-Buxoro</pre>\n"
        "🖼 <b>Rasmli savol</b>: rasm yuboring va izohiga (caption) savol bilan "
        "variantlarni xuddi shunday yozing."
    )


@router.message(Command("qoshish"))
@router.message(F.text == ui.BTN_ADD)
async def cmd_add(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    uid = message.from_user.id
    cols = await db.owned_collections(uid)
    prefs = await db.get_prefs(uid)
    rows = [[(f"{'⭐️ ' if c['id'] == prefs['collection_id'] else ''}"
              f"{ui.shorten(c['title'], 26)} · {c['n']}", f"lib:addto:{c['id']}")]
            for c in cols]
    rows.append([("➕ Yangi baza ochish", "lib:new")])
    head = ("➕ Savollar qaysi bazaga qo'shilsin?\n\n"
            "<i>Savol faqat o'z bazangizga qo'shiladi. Kim ko'rishini keyin "
            "«🔐 Kim ko'ra oladi?» bo'limida belgilaysiz — sukut bo'yicha "
            "faqat o'zingiz ko'rasiz.</i>")
    if not cols:
        head = ("Sizda hali baza yo'q. «➕ Yangi baza ochish» ni bosing —\n"
                "u faqat sizga ko'rinadi, keyin xohlagan guruhingizga ochasiz.")
    await message.answer(head, reply_markup=ui.kb(rows))


@router.callback_query(F.data == "lib:import")
async def cb_import(call: types.CallbackQuery, state: FSMContext) -> None:
    col_id = await _own_collection(call.from_user.id)
    await _arm_upload(call.message, state, col_id, call.from_user.id)
    await call.answer()


@router.callback_query(F.data.startswith("lib:addto:"))
async def cb_addto(call: types.CallbackQuery, state: FSMContext) -> None:
    col_id = int(call.data.split(":")[2])
    await _arm_upload(call.message, state, col_id, call.from_user.id)
    await call.answer()


async def _arm_upload(message: types.Message, state: FSMContext, col_id: int,
                      user_id: int) -> None:
    col = await db.collection(col_id)
    if not col:
        await message.answer("Baza topilmadi.")
        return
    if col["owner_id"] != user_id:
        await message.answer(
            "⛔️ Savolni faqat o'z bazangizga qo'sha olasiz.\n"
            "«➕ Savol qo'shish» → «➕ Yangi baza ochish».")
        return
    await state.set_state(Lib.wait_file)
    await state.update_data(col_id=col_id)
    await message.answer(
        f"📚 Baza: <b>{ui.esc(col['title'])}</b>\n\n" + _upload_hint())


async def _own_collection(user_id: int) -> int:
    """Foydalanuvchining savol qo'shish uchun bazasi (kerak bo'lsa yaratiladi)."""
    prefs = await db.get_prefs(user_id)
    col = await db.collection(prefs["collection_id"]) if prefs["collection_id"] else None
    if col and col["owner_id"] == user_id:
        return col["id"]
    own = await db.owned_collections(user_id)
    if own:
        return own[0]["id"]
    col_id = await db.create_collection("Mening bazam", user_id, visibility="private")
    await db.set_pref(user_id, "collection_id", col_id)
    return col_id


@router.message(StateFilter(Lib.wait_file), F.document)
@router.message(F.document, F.chat.type == "private")
async def on_document(message: types.Message, state: FSMContext) -> None:
    doc = message.document
    name = (doc.file_name or "").lower()
    if not name.endswith((".json", ".zip", ".docx", ".doc", ".txt", ".md")):
        return
    if doc.file_size and doc.file_size > MAX_FILE:
        await message.answer("❌ Fayl juda katta (20 MB dan oshmasin).")
        return

    data = await state.get_data()
    col_id = data.get("col_id")
    col = await db.collection(col_id) if col_id else None
    if not col or col["owner_id"] != message.from_user.id:
        col_id = await _own_collection(message.from_user.id)

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

    if not await _materialize(result, message.from_user.id):
        await status.edit_text("❌ Rasmli savollarning rasmlarini yuklab bo'lmadi.")
        return
    await _preview(status, state, result, col_id, source=doc.file_name)


async def _materialize(result: importers.ImportResult, user_id: int) -> bool:
    """Savollardagi rasm havolalarini (ZIP ichidagi fayl, URL) serverga saqlab,
    nisbiy yo'lga almashtiradi. Rasmi yuklanmagan savol tashlab yuboriladi."""
    done: dict[str, str] = {}

    async def store(ref: str) -> str:
        if ref in done:
            return done[ref]
        if ref.startswith("zip://"):
            raw = result.files[ref]
        elif media.is_url(ref):
            raw = await media.fetch_url(ref)
        elif media.is_local(ref):
            return ref
        else:
            raise ValueError(f"rasm topilmadi: {ref}")
        done[ref] = await asyncio.to_thread(media.store_image, raw, user_id)
        return done[ref]

    kept, bad = [], 0
    for q in result.questions:
        try:
            if q.get("image"):
                q["image"] = await store(q["image"])
            if q.get("option_images"):
                q["option_images"] = [await store(r) for r in q["option_images"]]
            kept.append(q)
        except Exception:
            bad += 1
    result.files.clear()
    if bad:
        result.skipped += bad
        result.notes.append(f"⚠️ {bad} ta savolning rasmi yuklanmadi — o'tkazib yuborildi.")
    result.questions = kept
    return bool(kept)


@router.message(StateFilter(Lib.wait_file), F.photo)
async def on_photo(message: types.Message, state: FSMContext) -> None:
    """Rasm + izoh (caption) = bitta rasmli savol."""
    caption = (message.caption or "").strip()
    if not caption:
        await message.answer(
            "🖼 Rasmning izohiga (caption) savol va variantlarni yozing:\n"
            "<pre>Rasmda nechta uchburchak bor?\n+5\n-4\n-6</pre>")
        return
    try:
        result = importers.parse_txt(caption.encode("utf-8"))
    except importers.ImportError_ as exc:
        await message.answer(f"❌ {ui.esc(exc)}")
        return
    if result.count != 1:
        await message.answer("🖼 Bitta rasmga bitta savol yozing (variantlari bilan).")
        return
    buf = await message.bot.download(message.photo[-1])
    try:
        rel = await asyncio.to_thread(media.store_image, buf.read(), message.from_user.id)
    except ValueError as exc:
        await message.answer(f"❌ {ui.esc(exc)}")
        return
    result.questions[0]["image"] = rel
    data = await state.get_data()
    col_id = data.get("col_id")
    col = await db.collection(col_id) if col_id else None
    if not col or col["owner_id"] != message.from_user.id:
        col_id = await _own_collection(message.from_user.id)
    status = await message.answer("⏳ Tahlil qilinmoqda…")
    await _preview(status, state, result, col_id, source="rasm")


@router.message(StateFilter(Lib.wait_file), F.text, ~F.text.startswith("/"))
async def on_text_block(message: types.Message, state: FSMContext) -> None:
    if message.text in {ui.BTN_CLASSIC, ui.BTN_PRO, ui.BTN_IQ, ui.BTN_LIB, ui.BTN_ADD,
                        ui.BTN_STATS, ui.BTN_SETTINGS, ui.BTN_HELP}:
        await state.clear()
        return
    data = await state.get_data()
    col_id = data.get("col_id")
    col = await db.collection(col_id) if col_id else None
    if not col or col["owner_id"] != message.from_user.id:
        col_id = await _own_collection(message.from_user.id)
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
        pic = "🖼 " if q.get("image") else ""
        lines.append(f"\n<b>{pic}{ui.esc(ui.shorten(q['text'], 150))}</b>")
        if q.get("option_images"):
            lines.append(f"🖼 Variantlar: {len(q['option_images'])} ta rasm · "
                         f"to'g'ri javob: <b>{ui.LETTERS[q['correct']]}</b>")
        else:
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
            [("🔐 Kim ko'ra oladi?", f"lib:perm:{col_id}")],
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
