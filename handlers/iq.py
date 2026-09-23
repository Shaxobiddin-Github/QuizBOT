"""3-rejim: IQ test — vaqt cheklangan mantiqiy test."""
from __future__ import annotations

import asyncio
import contextlib
import random
from datetime import datetime, timedelta, timezone

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command

import db
import ui

router = Router(name="iq")

QUESTION_COUNT = 20
TIME_LIMIT_MIN = 20
IQ_TITLE = "IQ test — mantiq va zakovat"

RULES = (
    "🧩 <b>IQ test</b>\n\n"
    f"• <b>{QUESTION_COUNT} ta savol</b> — oson savoldan qiyiniga qarab\n"
    f"• <b>{TIME_LIMIT_MIN} daqiqa</b> umumiy vaqt\n"
    "• Savollar orasida erkin yurish mumkin, javobni o'zgartira olasiz\n"
    "• To'g'ri javob test tugagunicha ko'rsatilmaydi\n"
    "• Qiyinroq savol ko'proq ball keltiradi\n\n"
    "<b>Bo'limlar:</b> sonlar ketma-ketligi, harflar, analogiya, "
    "ortiqchasini top, mantiqiy masalalar, matematik mantiq\n\n"
    "<i>⚠️ Natija — taxminiy ko'rsatkich. Bu rasmiy, standartlashtirilgan "
    "IQ testi emas, o'zingizni sinab ko'rish uchun mo'ljallangan.</i>"
)


def grade_iq(score: int) -> tuple[str, str]:
    if score >= 130:
        return "Juda yuqori", "🌟"
    if score >= 115:
        return "Yuqori", "🏆"
    if score >= 100:
        return "O'rtachadan yuqori", "🥇"
    if score >= 85:
        return "O'rtacha", "🙂"
    return "O'rtachadan past", "📘"


async def iq_collection() -> int | None:
    row = await db.fetch_one(
        "SELECT id FROM collections WHERE COALESCE(kind,'quiz')='iq' ORDER BY id LIMIT 1")
    return row["id"] if row else None


# ------------------------------------------------------------------- boshlash
@router.message(Command("iq"))
@router.message(F.text == ui.BTN_IQ)
async def open_iq(message: types.Message) -> None:
    await db.touch_user(message.from_user.id, message.from_user.full_name,
                        message.from_user.username)
    col_id = await iq_collection()
    if not col_id or not await db.count_questions(col_id):
        await message.answer("🧩 IQ savollar bazasi hali tayyor emas.")
        return
    best = await db.fetch_one(
        """SELECT settings FROM sessions
           WHERE owner_id=? AND mode='iq' AND status='done'
           ORDER BY id DESC LIMIT 1""", (message.from_user.id,))
    extra = ""
    if best:
        import json
        prev = json.loads(best["settings"]).get("result")
        if prev:
            extra = f"\n\n📌 Oxirgi natijangiz: <b>{prev}</b>"
    await message.answer(RULES + extra,
                         reply_markup=ui.kb([[("▶️ Testni boshlash", "iq:go")]]))


@router.callback_query(F.data == "iq:go")
async def cb_go(call: types.CallbackQuery) -> None:
    await call.answer()
    await start_test(call.message, call.from_user)


async def start_test(message: types.Message, user: types.User) -> None:
    col_id = await iq_collection()
    if not col_id:
        return
    rows = await db.fetch_all(
        "SELECT id, COALESCE(difficulty,2) AS d FROM questions WHERE collection_id=?",
        (col_id,))
    by_diff: dict[int, list[int]] = {}
    for r in rows:
        by_diff.setdefault(r["d"], []).append(r["id"])
    for ids in by_diff.values():
        random.shuffle(ids)

    picked: list[int] = []
    for d in sorted(by_diff):                       # osondan qiyinga
        picked.extend(by_diff[d])
    if len(picked) > QUESTION_COUNT:
        # har darajadan proporsional olamiz, tartibi saqlanadi
        step = len(picked) / QUESTION_COUNT
        picked = [picked[int(i * step)] for i in range(QUESTION_COUNT)]

    questions = await db.questions_by_ids(picked)
    picked = [q for q in picked if q in questions]
    perm = []
    for qid in picked:
        order = list(range(len(questions[qid]["options"])))
        random.shuffle(order)
        perm.append(order)

    await db.abort_active(user.id)
    deadline = datetime.now(timezone.utc) + timedelta(minutes=TIME_LIMIT_MIN)
    settings = {"perm": perm, "deadline": deadline.isoformat(timespec="seconds"),
                "minutes": TIME_LIMIT_MIN}
    sid = await db.create_session(user.id, message.chat.id, col_id, "iq", picked, settings)
    text, markup = await render(sid, 0, user.id)
    await message.answer(text, reply_markup=markup)
    asyncio.create_task(_deadline_watch(message, sid, TIME_LIMIT_MIN * 60))


async def _deadline_watch(message: types.Message, sid: int, seconds: float) -> None:
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.sleep(seconds + 2)
        session = await db.get_session(sid)
        if session and session["status"] == "active":
            await db.finish_session(sid, "timeout")
            with contextlib.suppress(Exception):
                await message.answer("⏰ <b>Vaqt tugadi!</b>",
                                     reply_markup=ui.kb([[("📊 Natijani ko'rish",
                                                           f"iq:res:{sid}")]]))


# --------------------------------------------------------------------- render
def _left(session: dict) -> float:
    deadline = datetime.fromisoformat(session["settings"]["deadline"])
    return (deadline - datetime.now(timezone.utc)).total_seconds()


async def render(sid: int, index: int, user_id: int) -> tuple[str, types.InlineKeyboardMarkup]:
    session = await db.get_session(sid)
    if not session:
        return "Sessiya topilmadi.", ui.kb([[("🏠 Menyu", "pro:home")]])
    total = len(session["q_ids"])
    index = max(0, min(index, total - 1))
    q = await db.question(session["q_ids"][index])
    order = session["settings"]["perm"][index]
    shown = [q["options"][i] for i in order]

    rows_ans = await db.session_answers(sid, user_id)
    by_index = {r["q_index"]: r for r in rows_ans}
    chosen = by_index[index]["chosen"] if index in by_index else None
    left = _left(session)

    head = (f"🧩 <b>IQ test</b>  ·  <b>{index + 1}/{total}</b>\n"
            f"{ui.progress_bar(len(by_index), total)} javob berildi: {len(by_index)}"
            f"  ·  ⏳ <b>{ui.fmt_time(max(0, left))}</b>\n")
    body = (f"\n<i>{ui.esc(q['category'])} · {'⭐' * q['difficulty']}</i>\n"
            f"<b>{ui.esc(q['text'])}</b>\n\n"
            + ui.render_options(shown, chosen))

    letters = [(ui.LETTERS[i] + (" 🔵" if chosen == i else ""),
                f"iq:a:{sid}:{index}:{i}") for i in range(len(shown))]
    rows = [letters[i:i + 4] for i in range(0, len(letters), 4)]
    nav = []
    if index > 0:
        nav.append(("◀️", f"iq:g:{sid}:{index - 1}"))
    nav.append((f"🗺 {index + 1}/{total}", f"iq:map:{sid}"))
    if index < total - 1:
        nav.append(("▶️", f"iq:g:{sid}:{index + 1}"))
    rows.append(nav)
    rows.append([(f"🏁 Yakunlash ({len(by_index)}/{total})", f"iq:fin:{sid}")])
    return head + body, ui.kb(rows)


async def _edit(call: types.CallbackQuery, sid: int, index: int) -> None:
    text, markup = await render(sid, index, call.from_user.id)
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=markup)


async def _guard(call: types.CallbackQuery, sid: int) -> dict | None:
    session = await db.get_session(sid)
    if not session:
        await call.answer("Sessiya topilmadi.", show_alert=True)
        return None
    if session["owner_id"] != call.from_user.id:
        await call.answer("Bu sizning testingiz emas.", show_alert=True)
        return None
    if session["status"] != "active":
        await _results(call, sid)
        await call.answer("Test yakunlangan.")
        return None
    if _left(session) <= 0:
        await db.finish_session(sid, "timeout")
        await _results(call, sid)
        await call.answer("⏰ Vaqt tugadi!", show_alert=True)
        return None
    return session


# ------------------------------------------------------------------ callbacks
@router.callback_query(F.data.startswith("iq:a:"))
async def on_answer(call: types.CallbackQuery) -> None:
    _, _, sid, index, opt = call.data.split(":")
    sid, index, opt = int(sid), int(index), int(opt)
    session = await _guard(call, sid)
    if session is None:
        return
    q = await db.question(session["q_ids"][index])
    order = session["settings"]["perm"][index]
    correct = order.index(q["correct"])
    await db.save_answer(sid, call.from_user.id, call.from_user.full_name,
                         index, q["id"], opt, opt == correct)
    await call.answer("Javob qabul qilindi")

    done = {r["q_index"] for r in await db.session_answers(sid, call.from_user.id)}
    total = len(session["q_ids"])
    nxt = next((i for i in range(index + 1, total) if i not in done), None)
    if nxt is None:
        nxt = next((i for i in range(0, total) if i not in done), None)
    if nxt is None:
        await db.finish_session(sid)
        await _results(call, sid)
        return
    await db.set_cursor(sid, nxt)
    await _edit(call, sid, nxt)


@router.callback_query(F.data.startswith("iq:g:"))
async def on_goto(call: types.CallbackQuery) -> None:
    _, _, sid, index = call.data.split(":")
    if await _guard(call, int(sid)) is None:
        return
    await db.set_cursor(int(sid), int(index))
    await _edit(call, int(sid), int(index))
    await call.answer()


@router.callback_query(F.data.startswith("iq:map:"))
async def on_map(call: types.CallbackQuery) -> None:
    sid = int(call.data.split(":")[2])
    session = await _guard(call, sid)
    if session is None:
        return
    total = len(session["q_ids"])
    done = {r["q_index"] for r in await db.session_answers(sid, call.from_user.id)}
    rows, cur = [], []
    for i in range(total):
        cur.append((("🔵" if i in done else "") + str(i + 1), f"iq:g:{sid}:{i}"))
        if len(cur) == 5:
            rows.append(cur)
            cur = []
    if cur:
        rows.append(cur)
    rows.append([("↩️ Savolga qaytish", f"iq:g:{sid}:{session['cursor']}")])
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(
            f"🗺 <b>Savollar</b> — {len(done)}/{total} javob berildi\n"
            f"⏳ Qolgan vaqt: <b>{ui.fmt_time(max(0, _left(session)))}</b>",
            reply_markup=ui.kb(rows))
    await call.answer()


@router.callback_query(F.data.startswith("iq:fin:"))
async def on_finish(call: types.CallbackQuery) -> None:
    sid = int(call.data.split(":")[2])
    session = await db.get_session(sid)
    if not session or session["owner_id"] != call.from_user.id:
        await call.answer()
        return
    total = len(session["q_ids"])
    done = len(await db.session_answers(sid, call.from_user.id))
    if session["status"] == "active" and done < total:
        await call.message.edit_text(
            f"🏁 <b>Testni yakunlaysizmi?</b>\n\n"
            f"Javob berilgan: <b>{done}/{total}</b>\n"
            f"Qolgan {total - done} ta savol xato hisoblanadi.",
            reply_markup=ui.kb([[("✅ Ha, yakunlash", f"iq:fin2:{sid}")],
                                [("↩️ Davom etish", f"iq:g:{sid}:{session['cursor']}")]]))
        await call.answer()
        return
    await _results(call, sid)
    await call.answer()


@router.callback_query(F.data.startswith("iq:fin2:"))
@router.callback_query(F.data.startswith("iq:res:"))
async def on_finish_do(call: types.CallbackQuery) -> None:
    await _results(call, int(call.data.split(":")[2]))
    await call.answer()


# -------------------------------------------------------------------- natija
async def _results(call: types.CallbackQuery, sid: int) -> None:
    session = await db.get_session(sid)
    if not session or session["owner_id"] != call.from_user.id:
        return
    if session["status"] == "active":
        await db.finish_session(sid)
    uid = call.from_user.id
    q_ids = session["q_ids"]
    questions = await db.questions_by_ids(q_ids)
    answers = {r["q_index"]: r for r in await db.session_answers(sid, uid)}

    total_w = correct_w = 0
    by_cat: dict[str, list[int]] = {}
    n_correct = 0
    for i, qid in enumerate(q_ids):
        q = questions.get(qid)
        if not q:
            continue
        w = q["difficulty"]
        total_w += w
        cat = q["category"] or "Boshqa"
        stat = by_cat.setdefault(cat, [0, 0])
        stat[1] += 1
        row = answers.get(i)
        if row and row["is_correct"]:
            correct_w += w
            n_correct += 1
            stat[0] += 1

    raw = correct_w / total_w if total_w else 0
    score = max(70, min(140, round(70 + raw * 70)))
    label, emoji = grade_iq(score)
    started = datetime.fromisoformat(session["started_at"])
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()

    lines = [
        "🧩 <b>IQ test yakunlandi</b>\n",
        f"{emoji} Taxminiy ko'rsatkich: <b>{score}</b>",
        f"📈 Daraja: <b>{label}</b>",
        f"{ui.progress_bar(round(raw * 100), 100, 16)}\n",
        f"✅ To'g'ri javoblar: <b>{n_correct}/{len(q_ids)}</b>",
        f"⚖️ Qiyinlik bo'yicha ball: <b>{correct_w}/{total_w}</b>",
        f"⏱ Sarflangan vaqt: <b>{ui.fmt_time(elapsed)}</b>\n",
        "<b>Bo'limlar bo'yicha:</b>",
    ]
    for cat, (ok, tot) in sorted(by_cat.items(), key=lambda x: -x[1][1]):
        bar = ui.progress_bar(ok, tot, 6)
        lines.append(f"• {ui.esc(cat)} — {bar} {ok}/{tot}")
    lines.append("\n<i>⚠️ Bu taxminiy ko'rsatkich. Rasmiy, standartlashtirilgan "
                 "IQ testi emas — o'zingizni sinash uchun mo'ljallangan.</i>")

    import json
    settings = dict(session["settings"])
    settings["result"] = score
    await db.execute("UPDATE sessions SET settings=? WHERE id=?",
                     (json.dumps(settings, ensure_ascii=False), sid))

    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text("\n".join(lines), reply_markup=ui.kb([
            [("🔍 Javoblar tahlili", f"iq:rev:{sid}:0")],
            [("🔁 Qayta urinish", "iq:go"), ("🏠 Menyu", "pro:home")],
        ]))


@router.callback_query(F.data.startswith("iq:rev:"))
async def on_review(call: types.CallbackQuery) -> None:
    _, _, sid, page = call.data.split(":")
    sid, page = int(sid), int(page)
    session = await db.get_session(sid)
    if not session or session["owner_id"] != call.from_user.id:
        await call.answer()
        return
    q_ids = session["q_ids"]
    questions = await db.questions_by_ids(q_ids)
    answers = {r["q_index"]: r for r in await db.session_answers(sid, call.from_user.id)}

    per = 4
    pages = (len(q_ids) + per - 1) // per
    page = max(0, min(page, pages - 1))
    out = [f"🔍 <b>Javoblar tahlili</b> (sahifa {page + 1}/{pages})\n"]
    for i in range(page * per, min((page + 1) * per, len(q_ids))):
        q = questions.get(q_ids[i])
        if not q:
            continue
        order = session["settings"]["perm"][i]
        shown = [q["options"][j] for j in order]
        correct = order.index(q["correct"])
        row = answers.get(i)
        icon = "✅" if row and row["is_correct"] else ("❌" if row else "⏭")
        out.append(f"{icon} <b>{i + 1}.</b> {ui.esc(q['text'])}")
        if row and not row["is_correct"] and 0 <= row["chosen"] < len(shown):
            out.append(f"   ✗ Siz: <i>{ui.esc(shown[row['chosen']])}</i>")
        out.append(f"   ✓ To'g'ri: <b>{ui.esc(shown[correct])}</b>")
        if q["explanation"]:
            out.append(f"   💡 <i>{ui.esc(q['explanation'])}</i>")
        out.append("")

    nav = []
    if page > 0:
        nav.append(("⬅️", f"iq:rev:{sid}:{page - 1}"))
    if page < pages - 1:
        nav.append(("➡️", f"iq:rev:{sid}:{page + 1}"))
    keyboard = [nav] if nav else []
    keyboard.append([("📊 Natijaga qaytish", f"iq:res:{sid}")])
    body = "\n".join(out)
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(body[:4000], reply_markup=ui.kb(keyboard))
    await call.answer()
