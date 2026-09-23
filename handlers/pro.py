"""2-rejim: Pro — bitta xabar ichida boshqariladigan zamonaviy test."""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone

from aiogram import F, Router, types

import access
import db
import media
import ui

router = Router(name="pro")

# (session_id, q_index) -> yashirilgan variantlar (50:50)
FIFTY: dict[tuple[int, int], set[int]] = {}


def forget(sid: int) -> None:
    """Sessiya yopilganda 50:50 ma'lumotini tozalash."""
    for key in [k for k in FIFTY if k[0] == sid]:
        FIFTY.pop(key, None)


# ------------------------------------------------------------------ boshlash
async def start_quiz(message: types.Message, user: types.User,
                     only_mistakes: bool = False) -> None:
    col_id = await access.ensure_collection(message.bot, user.id)
    prefs = await db.get_prefs(user.id)

    if only_mistakes:
        q_ids = await db.weak_questions(user.id, max(prefs["count"] or 30, 10))
        if not q_ids:
            await message.answer("🎉 Sizda takrorlash uchun xato savol yo'q!")
            return
    else:
        if not col_id or not await db.count_questions(col_id):
            await message.answer(
                "📚 Sizga ochiq baza yo'q.\n«➕ Savol qo'shish» orqali o'z bazangizni "
                "yarating yoki guruhdoshingizdan o'z bazasini shu guruhga ochishni so'rang.")
            return
        q_ids = await db.pick_questions(
            col_id, prefs["count"], user.id,
            skip_learned=bool(prefs["skip_learned"]), shuffle=bool(prefs["shuffle_q"]))
    if not q_ids:
        await message.answer("Mos savol topilmadi. Sozlamalarni o'zgartirib ko'ring.")
        return

    questions = await db.questions_by_ids(q_ids)
    q_ids = [q for q in q_ids if q in questions]
    perm = [db.make_perm(questions[qid], bool(prefs["shuffle_a"])) for qid in q_ids]

    from handlers import classic
    await classic.stop_private(user.id)
    settings = {"instant": prefs["instant"], "perm": perm,
                "mistakes": int(only_mistakes)}
    sid = await db.create_session(user.id, message.chat.id, col_id or 0, "pro",
                                  q_ids, settings)
    text, markup, photo = await render(message.bot, sid, 0, user.id)
    await media.send(message.bot, message.chat.id, text, markup, photo)


# ------------------------------------------------------------------- render
async def _ctx(sid: int, index: int):
    session = await db.get_session(sid)
    if not session or not session["q_ids"]:
        return None
    index = max(0, min(index, len(session["q_ids"]) - 1))
    qid = session["q_ids"][index]
    q = await db.question(qid)
    if not q:
        return None
    order = session["settings"]["perm"][index]
    shown = [q["options"][i] for i in order]
    correct = order.index(q["correct"])
    return session, index, q, shown, correct


def _options_block(q: dict, shown: list[str], chosen, correct, reveal: bool,
                   hidden: set[int]) -> str:
    if not media.has_option_images(q):
        return ui.render_options(shown, chosen, correct, reveal, hidden)
    letters = ui.LETTERS[:len(shown)]
    out = f"<i>🖼 Javob variantlari rasmda: {letters[0]}–{letters[-1]}</i>"
    if hidden:
        out += "\n💡 50:50 — olib tashlandi: " + ", ".join(ui.LETTERS[i] for i in sorted(hidden))
    if chosen is not None:
        out += f"\nTanlangan: <b>{ui.LETTERS[chosen]}</b>"
    return out


def _answer_label(q: dict, shown: list[str], i: int) -> str:
    if media.has_option_images(q):
        return ui.LETTERS[i]
    return f"{ui.LETTERS[i]}) {ui.esc(shown[i])}"


async def render(bot, sid: int, index: int, user_id: int, reveal: bool = False):
    """-> (matn, klaviatura, rasm yoki None)"""
    ctx = await _ctx(sid, index)
    if ctx is None:
        return "Sessiya topilmadi.", ui.kb([[("🏠 Menyu", "pro:home")]]), None
    session, index, q, shown, correct = ctx
    total = len(session["q_ids"])

    rows_ans = await db.session_answers(sid, user_id)
    by_index = {r["q_index"]: r for r in rows_ans}
    answered = len(by_index)
    n_ok = sum(1 for r in rows_ans if r["is_correct"])
    n_bad = answered - n_ok

    mine = by_index.get(index)
    chosen = mine["chosen"] if mine else None
    instant = bool(session["settings"].get("instant", 1))
    show_truth = reveal or (instant and mine is not None)

    started = datetime.fromisoformat(session["started_at"])
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()

    col = await db.collection(session["collection_id"])
    title = col["title"] if col else "Xatolar ustida ish"
    if session["settings"].get("mistakes"):
        title = "🔁 Xatolar ustida ish"
    learned = await db.is_learned(user_id, q["id"])
    hidden = FIFTY.get((sid, index), set())

    head = (
        f"🧠 <b>Pro rejim</b> · {ui.esc(ui.shorten(title, 30))}\n"
        f"{ui.progress_bar(answered, total)} <b>{index + 1}/{total}</b>"
        f"  ·  ✅{n_ok} ❌{n_bad}  ·  ⏱ {ui.fmt_time(elapsed)}\n"
    )
    limit = 600 if media.has_media(q) else 3000
    body = (f"\n<b>{index + 1}-savol.</b> {ui.esc(ui.shorten(q['text'], limit))}"
            + ("  🎓" if learned else "") + "\n\n"
            + _options_block(q, shown, chosen, correct, show_truth, hidden))
    if show_truth and mine is not None:
        body += ("\n\n<b>✅ To'g'ri!</b>" if mine["is_correct"]
                 else f"\n\n<b>❌ Xato.</b> To'g'ri javob — "
                      f"<b>{_answer_label(q, shown, correct)}</b>")
        if q["explanation"]:
            body += f"\n<i>💡 {ui.esc(ui.shorten(q['explanation'], 300))}</i>"

    # --- klaviatura
    rows: list[list[tuple[str, str]]] = []
    if mine is None:
        letters = []
        for i in range(len(shown)):
            if i in hidden:
                continue
            letters.append((ui.LETTERS[i], f"pro:a:{sid}:{index}:{i}"))
        for i in range(0, len(letters), 4):
            rows.append(letters[i:i + 4])
    else:
        marks = []
        for i in range(len(shown)):
            icon = ui.LETTERS[i]
            if show_truth:
                icon += " ✅" if i == correct else (" ❌" if i == chosen else "")
            elif i == chosen:
                icon += " 🔵"
            marks.append((icon, "pro:noop"))
        for i in range(0, len(marks), 4):
            rows.append(marks[i:i + 4])

    nav = []
    if index > 0:
        nav.append(("◀️", f"pro:g:{sid}:{index - 1}"))
    nav.append((f"🗺 {index + 1}/{total}", f"pro:map:{sid}:0"))
    if index < total - 1:
        nav.append(("▶️", f"pro:g:{sid}:{index + 1}"))
    rows.append(nav)

    tools = []
    if mine is None and len(shown) - len(hidden) > 2:
        tools.append(("💡 50:50", f"pro:f:{sid}:{index}"))
    tools.append((f"🎓 {'O‘rganildi' if learned else 'O‘rgandim'}",
                  f"pro:l:{sid}:{index}"))
    rows.append(tools)
    rows.append([(f"🏁 Yakunlash ({answered}/{total})", f"pro:fin:{sid}")])
    return head + body, ui.kb(rows), await media.photo_for(bot, q)


async def _redraw(bot, message, user_id: int, sid: int, index: int,
                  reveal: bool = False) -> types.Message:
    text, markup, photo = await render(bot, sid, index, user_id, reveal)
    return await media.show(bot, message.chat.id, message, text, markup, photo)


async def _edit(call: types.CallbackQuery, sid: int, index: int,
                reveal: bool = False) -> types.Message:
    return await _redraw(call.bot, call.message, call.from_user.id, sid, index, reveal)


async def _show_text(call: types.CallbackQuery, text: str, markup) -> None:
    await media.show(call.bot, call.message.chat.id, call.message, text, markup)


async def _own(call: types.CallbackQuery, sid: int) -> dict | None:
    """Faqat sessiya egasi boshqara oladi."""
    session = await db.get_session(sid)
    if not session or session["mode"] not in ("pro", "classic"):
        await call.answer("Sessiya topilmadi.", show_alert=True)
        return None
    if session["owner_id"] != call.from_user.id:
        await call.answer("Bu sizning testingiz emas.", show_alert=True)
        return None
    return session


# ---------------------------------------------------------------- callbacks
@router.callback_query(F.data == "pro:noop")
async def noop(call: types.CallbackQuery) -> None:
    await call.answer("Bu savolga javob berilgan.")


@router.callback_query(F.data == "pro:home")
async def home(call: types.CallbackQuery) -> None:
    await call.message.answer("🏠 Bosh menyu",
                              reply_markup=ui.menu_for(call.message.chat))
    await call.answer()


@router.callback_query(F.data.startswith("pro:a:"))
async def on_answer(call: types.CallbackQuery) -> None:
    _, _, sid, index, opt = call.data.split(":")
    sid, index, opt = int(sid), int(index), int(opt)
    ctx = await _ctx(sid, index)
    if ctx is None:
        await call.answer("Sessiya topilmadi.", show_alert=True)
        return
    session, index, q, shown, correct = ctx
    if session["owner_id"] != call.from_user.id:
        await call.answer("Bu sizning testingiz emas.", show_alert=True)
        return
    if session["status"] != "active":
        await call.answer("Bu test allaqachon yakunlangan.", show_alert=True)
        return
    if not 0 <= opt < len(shown):
        await call.answer()
        return

    is_ok = opt == correct
    await db.save_answer(sid, call.from_user.id, call.from_user.full_name,
                         index, q["id"], opt, is_ok)
    await call.answer("✅ To'g'ri!" if is_ok else "❌ Xato")

    instant = bool(session["settings"].get("instant", 1))
    msg = await _edit(call, sid, index, reveal=instant)

    nxt = await _next_unanswered(sid, call.from_user.id, index)
    if nxt is None:
        await asyncio.sleep(1.0 if instant else 0.2)
        await _finish(call, sid, msg)
        return
    await asyncio.sleep(1.6 if instant else 0.15)
    fresh = await db.get_session(sid)
    if fresh and fresh["status"] == "active":
        await db.set_cursor(sid, nxt)
        await _redraw(call.bot, msg, call.from_user.id, sid, nxt)


async def _next_unanswered(sid: int, user_id: int, current: int) -> int | None:
    session = await db.get_session(sid)
    total = len(session["q_ids"])
    done = {r["q_index"] for r in await db.session_answers(sid, user_id)}
    for i in list(range(current + 1, total)) + list(range(0, current + 1)):
        if i not in done:
            return i
    return None


@router.callback_query(F.data.startswith("pro:g:"))
async def on_goto(call: types.CallbackQuery) -> None:
    _, _, sid, index = call.data.split(":")
    if await _own(call, int(sid)) is None:
        return
    await db.set_cursor(int(sid), int(index))
    await _edit(call, int(sid), int(index))
    await call.answer()


@router.callback_query(F.data.startswith("pro:f:"))
async def on_fifty(call: types.CallbackQuery) -> None:
    _, _, sid, index = call.data.split(":")
    sid, index = int(sid), int(index)
    if await _own(call, sid) is None:
        return
    ctx = await _ctx(sid, index)
    if ctx is None:
        await call.answer()
        return
    _, index, _, shown, correct = ctx
    wrong = [i for i in range(len(shown)) if i != correct]
    random.shuffle(wrong)
    keep = max(0, len(shown) - 2)
    FIFTY[(sid, index)] = set(wrong[:keep])
    await _edit(call, sid, index)
    await call.answer("💡 Ortiqcha variantlar olib tashlandi")


@router.callback_query(F.data.startswith("pro:l:"))
async def on_learned(call: types.CallbackQuery) -> None:
    _, _, sid, index = call.data.split(":")
    sid, index = int(sid), int(index)
    if await _own(call, sid) is None:
        return
    ctx = await _ctx(sid, index)
    if ctx is None:
        await call.answer()
        return
    _, index, q, _, _ = ctx
    state = await db.toggle_learned(call.from_user.id, q["id"])
    await _edit(call, sid, index, reveal=False)
    await call.answer("🎓 «O'rgandim» belgilandi" if state else "Belgi olib tashlandi")


@router.callback_query(F.data.startswith("pro:map:"))
async def on_map(call: types.CallbackQuery) -> None:
    _, _, sid, page = call.data.split(":")
    sid, page = int(sid), int(page)
    session = await _own(call, sid)
    if not session:
        return
    total = len(session["q_ids"])
    done = {r["q_index"]: r["is_correct"]
            for r in await db.session_answers(sid, call.from_user.id)}
    instant = bool(session["settings"].get("instant", 1))

    per_page = 40
    start, end = page * per_page, min((page + 1) * per_page, total)
    rows, cur = [], []
    for i in range(start, end):
        if i in done:
            label = (("✅" if done[i] else "❌") if instant else "🔵") + str(i + 1)
        else:
            label = str(i + 1)
        cur.append((label, f"pro:g:{sid}:{i}"))
        if len(cur) == 5:
            rows.append(cur)
            cur = []
    if cur:
        rows.append(cur)

    pager = []
    if page > 0:
        pager.append(("⬅️", f"pro:map:{sid}:{page - 1}"))
    if end < total:
        pager.append(("➡️", f"pro:map:{sid}:{page + 1}"))
    if pager:
        rows.append(pager)
    rows.append([("↩️ Savolga qaytish", f"pro:g:{sid}:{session['cursor']}")])
    await _show_text(call,
                     f"🗺 <b>Savollar xaritasi</b> — {len(done)}/{total} javob berilgan\n"
                     f"Istalgan raqamni bosing:", ui.kb(rows))
    await call.answer()


@router.callback_query(F.data.startswith("pro:fin:"))
async def on_finish_ask(call: types.CallbackQuery) -> None:
    sid = int(call.data.split(":")[2])
    session = await _own(call, sid)
    if not session:
        return
    total = len(session["q_ids"])
    done = len(await db.session_answers(sid, call.from_user.id))
    if done >= total or session["status"] != "active":
        await _finish(call, sid)
        await call.answer()
        return
    await _show_text(call,
                     f"🏁 <b>Testni yakunlaysizmi?</b>\n\n"
                     f"Javob berilgan: <b>{done}/{total}</b>\n"
                     f"Qolgan {total - done} ta savol javobsiz hisoblanadi.",
                     ui.kb([
                         [("✅ Ha, yakunlash", f"pro:fin2:{sid}")],
                         [("↩️ Davom etish", f"pro:g:{sid}:{session['cursor']}")],
                     ]))
    await call.answer()


@router.callback_query(F.data.startswith("pro:fin2:"))
async def on_finish_do(call: types.CallbackQuery) -> None:
    sid = int(call.data.split(":")[2])
    if await _own(call, sid) is None:
        return
    await _finish(call, sid)
    await call.answer()


async def _finish(call: types.CallbackQuery, sid: int, message=None) -> None:
    session = await db.get_session(sid)
    if not session or session["owner_id"] != call.from_user.id:
        return
    if session["status"] == "active":
        await db.finish_session(sid)
    forget(sid)
    uid = call.from_user.id
    total = len(session["q_ids"])
    rows = await db.session_answers(sid, uid)
    correct = sum(1 for r in rows if r["is_correct"])
    wrong = len(rows) - correct
    skipped = total - len(rows)
    pct = correct / total * 100 if total else 0
    name, emoji = ui.grade(pct)
    started = datetime.fromisoformat(session["started_at"])
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()

    text = (
        f"🏁 <b>Test yakunlandi</b>\n\n"
        f"{emoji}  <b>{correct} / {total}</b>   ({pct:.1f}%)\n"
        f"{ui.progress_bar(correct, total, 16)}\n"
        f"📈 Baho: <b>{name}</b>\n\n"
        f"✅ To'g'ri: <b>{correct}</b>\n"
        f"❌ Xato: <b>{wrong}</b>\n"
        f"⏭ Javobsiz: <b>{skipped}</b>\n"
        f"⏱ Vaqt: <b>{ui.fmt_time(elapsed)}</b>"
        + (f"  (o'rtacha {elapsed / max(len(rows), 1):.0f}s/savol)" if rows else "")
    )
    buttons = [[("❌ Xatolar tahlili", f"pro:rev:{sid}:w:0"),
                ("📋 Hammasi", f"pro:rev:{sid}:all:0")]]
    if wrong:
        buttons.append([("🔁 Xatolar ustida ishlash", "su:pro:mistakes")])
    buttons.append([("🔄 Yangi test", "su:pro:back"), ("🎯 Klassik", "su:classic:back")])
    await media.show(call.bot, call.message.chat.id, message or call.message, text,
                     ui.kb(buttons))


# ------------------------------------------------------------------- review
@router.callback_query(F.data.startswith("pro:rev:"))
async def on_review(call: types.CallbackQuery) -> None:
    _, _, sid, flt, page = call.data.split(":")
    sid, page = int(sid), int(page)
    session = await db.get_session(sid)
    if not session:
        await call.answer("Sessiya topilmadi.", show_alert=True)
        return
    rows = await db.session_answers(sid, call.from_user.id)
    if flt == "w":
        rows = [r for r in rows if not r["is_correct"]]
    elif flt == "r":
        rows = [r for r in rows if r["is_correct"]]
    titles = {"all": "📋 Barcha javoblar", "w": "❌ Xatolar", "r": "✅ To'g'ri javoblar"}

    if not rows:
        await call.answer("Bu bo'limda savol yo'q 🎉", show_alert=True)
        return

    per_page = 4
    pages = (len(rows) + per_page - 1) // per_page
    page = max(0, min(page, pages - 1))
    chunk = rows[page * per_page:(page + 1) * per_page]
    questions = await db.questions_by_ids([r["question_id"] for r in chunk])
    perms = session["settings"].get("perm") or []

    out = [f"{titles[flt]} — {len(rows)} ta  (sahifa {page + 1}/{pages})\n"]
    for r in chunk:
        q = questions.get(r["question_id"])
        if not q:
            continue
        idx = r["q_index"]
        order = perms[idx] if idx < len(perms) else list(range(len(q["options"])))
        shown = [q["options"][i] for i in order]
        correct = order.index(q["correct"])
        icon = "✅" if r["is_correct"] else "❌"
        pic = "🖼 " if media.has_media(q) else ""
        out.append(f"{icon} <b>{idx + 1}.</b> {pic}{ui.esc(ui.shorten(q['text'], 300))}")

        def label(k: int) -> str:
            return ui.LETTERS[k] if media.has_option_images(q) else ui.esc(shown[k])

        if not r["is_correct"] and 0 <= r["chosen"] < len(shown):
            out.append(f"   ✗ Siz: <i>{label(r['chosen'])}</i>")
        out.append(f"   ✓ To'g'ri: <b>{label(correct)}</b>")
        if q["explanation"]:
            out.append(f"   💡 <i>{ui.esc(ui.shorten(q['explanation'], 300))}</i>")
        out.append("")

    nav = []
    if page > 0:
        nav.append(("⬅️", f"pro:rev:{sid}:{flt}:{page - 1}"))
    if page < pages - 1:
        nav.append(("➡️", f"pro:rev:{sid}:{flt}:{page + 1}"))
    keyboard = [nav] if nav else []
    keyboard.append([
        ("❌ Xatolar", f"pro:rev:{sid}:w:0"),
        ("✅ To'g'ri", f"pro:rev:{sid}:r:0"),
        ("📋 Hammasi", f"pro:rev:{sid}:all:0"),
    ])
    keyboard.append([("🔄 Yangi test", "su:pro:back"), ("🏠 Menyu", "pro:home")])

    body = "\n".join(out)
    if len(body) > 4000:
        body = body[:3990] + "…"
    await _show_text(call, body, ui.kb(keyboard))
    await call.answer()
