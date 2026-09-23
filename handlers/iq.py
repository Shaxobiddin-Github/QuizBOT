"""3-rejim: IQ test — standartlashtirilgan testlar tuzilishi asosida.

Tuzilishi (Raven SPM/APM va WAIS «Matrix Reasoning» uslubida):
  * 30 ta savol, 30 daqiqa, osondan qiyinga;
  * uchta kognitiv soha: vizual-fazoviy (rasmli matritsalar, figuralar),
    son-miqdor va og'zaki-mantiqiy fikrlash;
  * ball — IRT (3PL) modeli, deviatsion IQ (M=100, SD=15), persentil va
    95% ishonch oralig'i bilan (`iq_score`).
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

from aiogram import F, Router, types
from aiogram.filters import Command

import bg
import db
import iq_score
import media
import ui

router = Router(name="iq")

QUESTION_COUNT = 30
TIME_LIMIT_MIN = 30
IQ_TITLE = "IQ test — mantiq va zakovat"

# bo'lim -> nechta savol olinadi (jami QUESTION_COUNT)
FORM = [
    ("Matritsalar (Raven)", 12),
    ("Figuralar ketma-ketligi", 3),
    ("Ortiqcha figura", 3),
    ("Sonlar ketma-ketligi", 4),
    ("Harflar ketma-ketligi", 2),
    ("Analogiya", 3),
    ("Ortiqchasini top", 1),
    ("Mantiqiy masala", 1),
    ("Matematik mantiq", 1),
]

DOMAINS = {
    "🔷 Vizual-fazoviy fikrlash": {"Matritsalar (Raven)", "Figuralar ketma-ketligi",
                                  "Ortiqcha figura"},
    "🔢 Son-miqdor mantiqi": {"Sonlar ketma-ketligi", "Matematik mantiq"},
    "💬 Og'zaki-mantiqiy fikrlash": {"Analogiya", "Ortiqchasini top", "Harflar ketma-ketligi",
                                    "Mantiqiy masala"},
}

RULES = (
    "🧩 <b>IQ test</b>\n\n"
    f"• <b>{QUESTION_COUNT} ta savol</b>, <b>{TIME_LIMIT_MIN} daqiqa</b> — osondan qiyinga\n"
    "• Rasmli matritsalar (Raven uslubi), figuralar ketma-ketligi, sonlar, "
    "analogiya va mantiqiy masalalar\n"
    "• Savollar orasida erkin yurish mumkin, javobni o'zgartira olasiz\n"
    "• To'g'ri javob test tugagunicha ko'rsatilmaydi, javobsiz savol — xato\n\n"
    "<b>Matritsa qanday yechiladi?</b> 3×3 jadvalda figuralar qator va ustun bo'yicha "
    "qonuniyat bilan o'zgaradi (soni, shakli, bo'yog'i, o'lchami, yo'nalishi). "
    "«?» o'rniga shu qonuniyatga mos variantni tanlang.\n\n"
    "<b>Ball qanday hisoblanadi?</b> Xalqaro psixometriya standarti — IRT modeli: "
    "qiyin savol ko'proq hissa qo'shadi, taxmin qilish ehtimoli hisobga olinadi. "
    "Natija deviatsion IQ shkalasida (o'rtacha 100, SD 15), persentil va ishonch "
    "oralig'i bilan beriladi.\n\n"
    "<i>⚠️ Bu skrining (taxminiy) test. Rasmiy diagnostika faqat psixolog o'tkazadigan "
    "standartlashtirilgan test (WAIS, Raven) orqali mumkin.</i>"
)


async def iq_collection() -> int | None:
    row = await db.fetch_one(
        "SELECT id FROM collections WHERE COALESCE(kind,'quiz')='iq' ORDER BY id LIMIT 1")
    return row["id"] if row else None


def _domain_of(category: str) -> str:
    for name, cats in DOMAINS.items():
        if category in cats:
            return name
    return "🧠 Boshqa"


# ------------------------------------------------------------ savol tanlash
def _stratified(items: list[dict], n: int, rng: random.Random) -> list[dict]:
    """Qiyinlik darajalari bo'yicha navbatma-navbat olamiz — har daraja qamraladi."""
    by_d: dict[int, list[dict]] = {}
    for it in items:
        by_d.setdefault(it["d"], []).append(it)
    for lst in by_d.values():
        rng.shuffle(lst)
    out: list[dict] = []
    levels = sorted(by_d)
    while len(out) < n and any(by_d[d] for d in levels):
        for d in levels:
            if by_d[d] and len(out) < n:
                out.append(by_d[d].pop())
    return out


def pick_form(rows: list[dict], rng: random.Random | None = None) -> list[int]:
    rng = rng or random.Random()
    pool = {r["id"]: r for r in rows}
    picked: list[dict] = []
    for cat, n in FORM:
        chosen = _stratified([r for r in pool.values() if r["cat"] == cat], n, rng)
        for r in chosen:
            pool.pop(r["id"])
        picked += chosen
    if len(picked) < QUESTION_COUNT:
        picked += _stratified(list(pool.values()), QUESTION_COUNT - len(picked), rng)
    rng.shuffle(picked)
    picked.sort(key=lambda r: r["d"])                     # osondan qiyinga
    return [r["id"] for r in picked]


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
    prev = await _last_result(message.from_user.id)
    extra = ""
    if prev:
        extra = f"\n\n📌 Oxirgi natijangiz: <b>IQ {prev['iq']}</b>"
        if prev.get("ci"):
            extra += f" (ishonch oralig'i {prev['ci'][0]}–{prev['ci'][1]})"
    await message.answer(RULES + extra,
                         reply_markup=ui.kb([[("▶️ Testni boshlash", "iq:go")]]))


async def _last_result(user_id: int) -> dict | None:
    row = await db.fetch_one(
        """SELECT settings FROM sessions
           WHERE owner_id=? AND mode='iq' AND status IN ('done','timeout')
           ORDER BY id DESC LIMIT 1""", (user_id,))
    if not row:
        return None
    res = json.loads(row["settings"] or "{}").get("result")
    if isinstance(res, int):              # eski formatdagi natija
        return {"iq": res}
    return res


@router.callback_query(F.data == "iq:go")
async def cb_go(call: types.CallbackQuery) -> None:
    await call.answer()
    await start_test(call.message, call.from_user)


async def start_test(message: types.Message, user: types.User) -> None:
    col_id = await iq_collection()
    if not col_id:
        return
    rows = await db.fetch_all(
        "SELECT id, COALESCE(difficulty,2) AS d, COALESCE(category,'') AS cat "
        "FROM questions WHERE collection_id=?", (col_id,))
    picked = pick_form([dict(r) for r in rows])
    questions = await db.questions_by_ids(picked)
    picked = [q for q in picked if q in questions]
    perm = [db.make_perm(questions[qid]) for qid in picked]

    from handlers import classic
    await classic.stop_private(user.id)
    deadline = datetime.now(timezone.utc) + timedelta(minutes=TIME_LIMIT_MIN)
    settings = {"perm": perm, "deadline": deadline.isoformat(timespec="seconds"),
                "minutes": TIME_LIMIT_MIN}
    sid = await db.create_session(user.id, message.chat.id, col_id, "iq", picked, settings)
    text, markup, photo = await render(message.bot, sid, 0, user.id)
    await media.send(message.bot, message.chat.id, text, markup, photo)
    bg.spawn(_deadline_watch(message.bot, message.chat.id, sid, TIME_LIMIT_MIN * 60))


async def _deadline_watch(bot, chat_id: int, sid: int, seconds: float) -> None:
    import asyncio
    await asyncio.sleep(seconds + 2)
    session = await db.get_session(sid)
    if session and session["status"] == "active":
        await db.finish_session(sid, "timeout")
        await bot.send_message(chat_id, "⏰ <b>Vaqt tugadi!</b>",
                               reply_markup=ui.kb([[("📊 Natijani ko'rish", f"iq:res:{sid}")]]))


# --------------------------------------------------------------------- render
def _left(session: dict) -> float:
    deadline = datetime.fromisoformat(session["settings"]["deadline"])
    return (deadline - datetime.now(timezone.utc)).total_seconds()


def question_body(q: dict, shown: list[str], chosen: int | None = None,
                  correct: int | None = None, reveal: bool = False) -> str:
    """Savol matni + variantlar. Variantlar rasm bo'lsa — matn o'rniga izoh."""
    limit = 600 if media.has_media(q) else 3000
    text = f"<b>{ui.esc(ui.shorten(q['text'], limit))}</b>\n\n"
    if media.has_option_images(q):
        letters = ui.LETTERS[:len(shown)]
        text += f"<i>🖼 Javob variantlari rasmda: {letters[0]}–{letters[-1]}</i>"
        if chosen is not None:
            text += f"\nTanlangan: <b>{ui.LETTERS[chosen]}</b>"
        if reveal and correct is not None:
            text += f"\nTo'g'ri javob: <b>{ui.LETTERS[correct]}</b>"
        return text
    return text + ui.render_options([ui.shorten(o, 200) for o in shown], chosen, correct, reveal)


async def render(bot, sid: int, index: int, user_id: int):
    session = await db.get_session(sid)
    if not session:
        return "Sessiya topilmadi.", ui.kb([[("🏠 Menyu", "pro:home")]]), None
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
            + question_body(q, shown, chosen))

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
    photo = await media.photo_for(bot, q)
    return head + body, ui.kb(rows), photo


async def _show(call: types.CallbackQuery, text: str, markup, photo=None) -> None:
    await media.show(call.bot, call.message.chat.id, call.message, text, markup, photo)


async def _edit(call: types.CallbackQuery, sid: int, index: int) -> None:
    text, markup, photo = await render(call.bot, sid, index, call.from_user.id)
    await _show(call, text, markup, photo)


async def _guard(call: types.CallbackQuery, sid: int) -> dict | None:
    session = await db.get_session(sid)
    if not session or session["mode"] != "iq":
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
    total = len(session["q_ids"])
    if not 0 <= index < total:
        await call.answer()
        return
    q = await db.question(session["q_ids"][index])
    order = session["settings"]["perm"][index]
    if not q or not 0 <= opt < len(order):
        await call.answer()
        return
    correct = order.index(q["correct"])
    await db.save_answer(sid, call.from_user.id, call.from_user.full_name,
                         index, q["id"], opt, opt == correct)
    await call.answer("Javob qabul qilindi")

    done = {r["q_index"] for r in await db.session_answers(sid, call.from_user.id)}
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
    await _show(call,
                f"🗺 <b>Savollar</b> — {len(done)}/{total} javob berildi\n"
                f"⏳ Qolgan vaqt: <b>{ui.fmt_time(max(0, _left(session)))}</b>",
                ui.kb(rows))
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
        await _show(call,
                    f"🏁 <b>Testni yakunlaysizmi?</b>\n\n"
                    f"Javob berilgan: <b>{done}/{total}</b>\n"
                    f"Qolgan {total - done} ta savol xato hisoblanadi.",
                    ui.kb([[("✅ Ha, yakunlash", f"iq:fin2:{sid}")],
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
def _pct_text(p: float) -> str:
    if p >= 99.5:
        return ">99"
    if p < 0.5:
        return "<1"
    return str(round(p))


async def compute(sid: int, user_id: int) -> tuple[iq_score.Report, dict, int, int]:
    session = await db.get_session(sid)
    q_ids = session["q_ids"]
    questions = await db.questions_by_ids(q_ids)
    answers = {r["q_index"]: r for r in await db.session_answers(sid, user_id)}
    items, by_dom, n_correct = [], {}, 0
    for i, qid in enumerate(q_ids):
        q = questions.get(qid)
        if not q:
            continue
        ok = bool(answers.get(i) and answers[i]["is_correct"])
        n_correct += ok
        items.append(iq_score.Item(q["difficulty"], len(q["options"]), ok))
        stat = by_dom.setdefault(_domain_of(q["category"]), [0, 0])
        stat[0] += ok
        stat[1] += 1
    return iq_score.report(items), by_dom, n_correct, len(items)


async def _results(call: types.CallbackQuery, sid: int) -> None:
    session = await db.get_session(sid)
    if not session or session["owner_id"] != call.from_user.id or session["mode"] != "iq":
        return
    if session["status"] == "active":
        await db.finish_session(sid)
    uid = call.from_user.id
    rep, by_dom, n_correct, total = await compute(sid, uid)
    started = datetime.fromisoformat(session["started_at"])
    finished = session.get("finished_at")
    end = datetime.fromisoformat(finished) if finished else datetime.now(timezone.utc)
    elapsed = min((end - started).total_seconds(), TIME_LIMIT_MIN * 60)
    pct = _pct_text(rep.percentile)

    lines = [
        "🧩 <b>IQ test yakunlandi</b>\n",
        f"{rep.emoji} IQ: <b>{rep.iq}</b>",
        f"📏 95% ishonch oralig'i: <b>{rep.ci_low}–{rep.ci_high}</b>",
        f"📈 Daraja: <b>{rep.label}</b> <i>(WAIS-IV tasnifi)</i>",
        f"👥 Persentil: <b>{pct}</b> — natijangiz odamlarning taxminan {pct}% idan yuqori",
        f"{ui.progress_bar(round(rep.percentile), 100, 16)}\n",
        f"✅ To'g'ri javoblar: <b>{n_correct}/{total}</b>",
        f"⏱ Sarflangan vaqt: <b>{ui.fmt_time(elapsed)}</b>\n",
        "<b>Sohalar bo'yicha:</b>",
    ]
    for dom, (ok, tot) in by_dom.items():
        lines.append(f"{dom} — {ui.progress_bar(ok, tot, 6)} {ok}/{tot}")

    earlier = await db.fetch_one(
        """SELECT COUNT(*) AS n FROM sessions WHERE owner_id=? AND mode='iq'
           AND status IN ('done','timeout') AND id<?""", (uid, sid))
    if earlier and earlier["n"]:
        lines.append("\n<i>🔁 Testni qayta topshirganda «mashq effekti» natijani biroz "
                     "oshirishi mumkin — birinchi urinish eng ishonchlisi.</i>")
    lines.append("\n<i>ℹ️ Hisob: IRT (3PL) modeli, deviatsion IQ shkalasi (o'rtacha 100, "
                 "SD 15). Bu skrining natijasi — rasmiy diagnostika uchun psixolog "
                 "o'tkazadigan standartlashtirilgan test (WAIS, Raven) zarur.</i>")

    settings = dict(session["settings"])
    settings["result"] = {"iq": rep.iq, "ci": [rep.ci_low, rep.ci_high],
                          "percentile": round(rep.percentile, 1), "correct": n_correct}
    await db.execute("UPDATE sessions SET settings=? WHERE id=?",
                     (json.dumps(settings, ensure_ascii=False), sid))

    await _show(call, "\n".join(lines), ui.kb([
        [("🔍 Javoblar tahlili", f"iq:rev:{sid}:0")],
        [("🔁 Qayta urinish", "iq:go"), ("🏠 Menyu", "pro:home")],
    ]))


# ------------------------------------------------------------------- tahlil
REVIEW_PER_PAGE = 5


@router.callback_query(F.data.startswith("iq:rev:"))
async def on_review(call: types.CallbackQuery) -> None:
    _, _, sid, page = call.data.split(":")
    sid, page = int(sid), int(page)
    session = await db.get_session(sid)
    if not session or session["owner_id"] != call.from_user.id or session["status"] == "active":
        await call.answer()
        return
    q_ids = session["q_ids"]
    questions = await db.questions_by_ids(q_ids)
    answers = {r["q_index"]: r for r in await db.session_answers(sid, call.from_user.id)}

    per = REVIEW_PER_PAGE
    pages = (len(q_ids) + per - 1) // per
    page = max(0, min(page, pages - 1))
    out = [f"🔍 <b>Javoblar tahlili</b> (sahifa {page + 1}/{pages})\n"]
    see = []
    for i in range(page * per, min((page + 1) * per, len(q_ids))):
        q = questions.get(q_ids[i])
        if not q:
            continue
        order = session["settings"]["perm"][i]
        shown = [q["options"][j] for j in order]
        correct = order.index(q["correct"])
        row = answers.get(i)
        icon = "✅" if row and row["is_correct"] else ("❌" if row else "⏭")
        pic = "🖼 " if media.has_media(q) else ""
        out.append(f"{icon} <b>{i + 1}.</b> {pic}{ui.esc(ui.shorten(q['text'], 160))}")

        def label(k: int) -> str:
            return ui.LETTERS[k] if media.has_option_images(q) else ui.esc(shown[k])

        if row and not row["is_correct"] and 0 <= row["chosen"] < len(shown):
            out.append(f"   ✗ Siz: <i>{label(row['chosen'])}</i>")
        out.append(f"   ✓ To'g'ri: <b>{label(correct)}</b>")
        if q["explanation"]:
            out.append(f"   💡 <i>{ui.esc(ui.shorten(q['explanation'], 300))}</i>")
        out.append("")
        if media.has_media(q):
            see.append((f"🖼 {i + 1}", f"iq:see:{sid}:{i}"))

    keyboard = [see[k:k + 5] for k in range(0, len(see), 5)]
    nav = []
    if page > 0:
        nav.append(("⬅️", f"iq:rev:{sid}:{page - 1}"))
    if page < pages - 1:
        nav.append(("➡️", f"iq:rev:{sid}:{page + 1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([("📊 Natijaga qaytish", f"iq:res:{sid}")])
    await _show(call, "\n".join(out)[:4000], ui.kb(keyboard))
    await call.answer()


@router.callback_query(F.data.startswith("iq:see:"))
async def on_see(call: types.CallbackQuery) -> None:
    """Tahlilda rasmli savolni to'g'ri javobi bilan ko'rsatish."""
    _, _, sid, index = call.data.split(":")
    sid, index = int(sid), int(index)
    session = await db.get_session(sid)
    if not session or session["owner_id"] != call.from_user.id or session["status"] == "active":
        await call.answer()
        return
    if not 0 <= index < len(session["q_ids"]):
        await call.answer()
        return
    q = await db.question(session["q_ids"][index])
    order = session["settings"]["perm"][index]
    shown = [q["options"][i] for i in order]
    correct = order.index(q["correct"])
    row = next((r for r in await db.session_answers(sid, call.from_user.id)
                if r["q_index"] == index), None)
    chosen = row["chosen"] if row else None
    text = (f"<b>{index + 1}-savol</b> · <i>{ui.esc(q['category'])} · {'⭐' * q['difficulty']}</i>\n"
            + question_body(q, shown, chosen, correct, reveal=True))
    if q["explanation"]:
        text += f"\n\n💡 <i>{ui.esc(ui.shorten(q['explanation'], 400))}</i>"
    page = index // REVIEW_PER_PAGE
    await _show(call, text, ui.kb([[("⬅️ Tahlilga qaytish", f"iq:rev:{sid}:{page}")]]),
                await media.photo_for(call.bot, q))
    await call.answer()
