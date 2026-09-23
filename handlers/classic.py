"""1-rejim: Telegram QuizBot uslubi — jonli quiz-poll'lar."""
from __future__ import annotations

import asyncio
import contextlib
import time

from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest

import access
import config
import db
import media
import ui

router = Router(name="classic")

# poll_id -> savol konteksti
POLLS: dict[str, dict] = {}
# session_id -> javob kutilayotgan hodisa (shaxsiy chatda tezroq o'tish uchun)
EVENTS: dict[int, asyncio.Event] = {}
# session_id -> ishlayotgan task
TASKS: dict[int, asyncio.Task] = {}


def cancel_runner(session_id: int) -> None:
    task = TASKS.pop(session_id, None)
    if task and not task.done():
        task.cancel()
    EVENTS.pop(session_id, None)


async def stop_private(user_id: int) -> None:
    """Foydalanuvchining shaxsiy chatdagi barcha faol testlarini to'xtatadi.
    Guruhdagi o'yinlar (u tashkilotchi bo'lsa ham) davom etadi."""
    from handlers import pro
    for sid in await db.private_active_ids(user_id):
        cancel_runner(sid)
        pro.forget(sid)
    await db.abort_active(user_id)


async def start_quiz(message: types.Message, user: types.User) -> None:
    col_id = await access.ensure_collection(message.bot, user.id)
    prefs = await db.get_prefs(user.id)
    if not col_id or not await db.count_questions(col_id):
        await message.answer(
            "📚 Sizga ochiq baza yo'q.\n«➕ Savol qo'shish» orqali o'z bazangizni "
            "yarating yoki guruhdoshingizdan o'z bazasini shu guruhga ochishni so'rang.")
        return

    await stop_private(user.id)
    q_ids = await db.pick_questions(
        col_id, prefs["count"], user.id,
        skip_learned=bool(prefs["skip_learned"]), shuffle=bool(prefs["shuffle_q"]))
    if not q_ids:
        await message.answer("Mos savol topilmadi. Sozlamalarni o'zgartirib ko'ring.")
        return

    questions = await db.questions_by_ids(q_ids)
    q_ids = [q for q in q_ids if q in questions]
    perm = [db.make_perm(questions[q], bool(prefs["shuffle_a"])) for q in q_ids]
    settings = {"timer": prefs["timer"], "shuffle_a": prefs["shuffle_a"], "perm": perm}
    sid = await db.create_session(user.id, message.chat.id, col_id, "classic", q_ids, settings)

    col = await db.collection(col_id)
    is_group = message.chat.type in ("group", "supergroup")
    await message.answer(
        f"🎯 <b>Klassik test boshlandi!</b>\n\n"
        f"📚 {ui.esc(col['title'])}\n"
        f"🔢 {len(q_ids)} ta savol · ⏱ har biriga {prefs['timer']} soniya\n"
        + ("👥 Guruh rejimi: barcha a'zolar qatnashadi, oxirida reyting chiqadi.\n"
           if is_group else "")
        + "\n<i>To'xtatish: /stop</i>",
        reply_markup=ui.kb([[("⏹ To'xtatish", f"cls:stop:{sid}")]]),
    )
    await asyncio.sleep(1.5)
    TASKS[sid] = asyncio.create_task(_run(message.bot, sid, is_group))


async def _run(bot: Bot, sid: int, is_group: bool) -> None:
    try:
        session = await db.get_session(sid)
        if not session:
            return
        q_ids = session["q_ids"]
        timer = int(session["settings"].get("timer", config.DEFAULT_TIMER))
        shuffle_a = bool(session["settings"].get("shuffle_a", 1))
        chat_id = session["chat_id"]
        questions = await db.questions_by_ids(q_ids)

        for index, qid in enumerate(q_ids):
            fresh = await db.get_session(sid)
            if not fresh or fresh["status"] != "active":
                return
            q = questions.get(qid)
            if not q:
                continue

            perm = session["settings"].get("perm")
            order = perm[index] if perm else db.make_perm(q, shuffle_a)
            shown = [q["options"][i] for i in order]
            correct = order.index(q["correct"])

            event = asyncio.Event()
            EVENTS[sid] = event
            poll_id = await _send_question(bot, chat_id, sid, index, len(q_ids), q, shown,
                                           correct, timer)
            await db.set_cursor(sid, index + 1)
            try:
                if is_group:
                    await asyncio.sleep(timer + 1)
                else:
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(event.wait(), timeout=timer + 2)
                    await asyncio.sleep(1.2)
            finally:
                EVENTS.pop(sid, None)
                POLLS.pop(poll_id, None)

        await db.finish_session(sid)
        await _show_results(bot, sid, is_group)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # pragma: no cover
        with contextlib.suppress(Exception):
            await bot.send_message(
                (await db.get_session(sid))["chat_id"],
                f"⚠️ Testda xatolik yuz berdi: <code>{ui.esc(exc)}</code>")
        await db.finish_session(sid, "error")
    finally:
        TASKS.pop(sid, None)


async def _send_question(bot: Bot, chat_id: int, sid: int, index: int, total: int,
                         q: dict, shown: list[str], correct: int, timer: int) -> str:
    header = f"❓ {index + 1}/{total}"
    img_opts = media.has_option_images(q)
    long_opts = any(len(o) > config.POLL_OPTION_LIMIT for o in shown)
    long_text = len(q["text"]) > config.POLL_QUESTION_LIMIT
    photo = await media.photo_for(bot, q)

    if photo or long_opts or long_text:
        # Savol (va rasm) alohida xabarda, poll'da faqat harflar
        from handlers import iq
        body = (f"{header}\n\n" + iq.question_body(q, shown)
                + "\n\n<i>Javobni quyidagi so'rovnomadan tanlang 👇</i>")
        await media.send(bot, chat_id, body, None, photo)
        poll_question = f"{header} — yuqoridagi savol"
        if img_opts:
            poll_options = list(ui.LETTERS[:len(shown)])
        else:
            poll_options = [f"{ui.LETTERS[i]}) {ui.shorten(o, config.POLL_OPTION_LIMIT - 4)}"
                            for i, o in enumerate(shown)]
    else:
        poll_question = ui.shorten(f"{header}  {q['text']}", config.POLL_QUESTION_LIMIT)
        poll_options = [ui.shorten(o, config.POLL_OPTION_LIMIT) for o in shown]

    right = ui.LETTERS[correct] if img_opts else shown[correct]
    explanation = q.get("explanation") or f"To'g'ri javob: {right}"
    msg = await bot.send_poll(
        chat_id=chat_id,
        question=poll_question,
        options=poll_options,
        type="quiz",
        correct_option_id=correct,
        is_anonymous=False,
        open_period=max(5, min(timer, 600)),
        explanation=ui.esc(ui.shorten(explanation, config.POLL_EXPLANATION_LIMIT)),
    )
    POLLS[msg.poll.id] = {
        "sid": sid, "index": index, "qid": q["id"],
        "correct": correct, "sent_at": time.monotonic(),
    }
    return msg.poll.id


@router.poll_answer()
async def on_poll_answer(poll_answer: types.PollAnswer) -> None:
    ctx = POLLS.get(poll_answer.poll_id)
    if not ctx or not poll_answer.option_ids:
        return
    user = poll_answer.user
    if user is None or user.is_bot:
        return
    chosen = poll_answer.option_ids[0]
    spent = int((time.monotonic() - ctx["sent_at"]) * 1000)
    await db.touch_user(user.id, user.full_name, user.username)
    await db.save_answer(
        ctx["sid"], user.id, user.full_name, ctx["index"], ctx["qid"],
        chosen, chosen == ctx["correct"], spent)

    session = await db.get_session(ctx["sid"])
    event = EVENTS.get(ctx["sid"])
    if event and session and session["owner_id"] == user.id:
        event.set()


async def _show_results(bot: Bot, sid: int, is_group: bool) -> None:
    session = await db.get_session(sid)
    if not session:
        return
    total = len(session["q_ids"])
    board = await db.leaderboard(sid)

    if not board:
        await bot.send_message(session["chat_id"],
                               "🏁 Test tugadi — hech kim javob bermadi.")
        return

    if is_group:
        lines = ["🏁 <b>Test yakunlandi!</b>", f"📋 Jami {total} ta savol\n",
                 "🏆 <b>Reyting</b>"]
        for i, r in enumerate(board, 1):
            pct = r["correct"] / total * 100
            lines.append(
                f"{ui.medal(i)} {ui.esc(r['user_name'])} — "
                f"<b>{r['correct']}/{total}</b> ({pct:.0f}%) · {r['ms'] / 1000:.0f}s")
        await bot.send_message(session["chat_id"], "\n".join(lines))
        return

    row = board[0]
    correct = row["correct"]
    pct = correct / total * 100
    name, emoji = ui.grade(pct)
    text = (
        f"🏁 <b>Test yakunlandi!</b>\n\n"
        f"{emoji} <b>{correct} / {total}</b>  ({pct:.1f}%)\n"
        f"📈 Baho: <b>{name}</b>\n"
        f"✅ To'g'ri: {correct}   ❌ Xato: {row['total'] - correct}   "
        f"⏭ Javobsiz: {total - row['total']}\n"
        f"⏱ Sarflangan vaqt: {ui.fmt_time(row['ms'] / 1000)}\n\n"
        f"{ui.progress_bar(correct, total, 16)}"
    )
    await bot.send_message(
        session["chat_id"], text,
        reply_markup=ui.kb([
            [("❌ Xatolarni ko'rish", f"pro:rev:{sid}:w:0")],
            [("🔁 Yana bir marta", "su:classic:go"), ("🧠 Pro rejim", "su:pro:back")],
        ]))


@router.callback_query(F.data.startswith("cls:stop:"))
async def on_stop(call: types.CallbackQuery) -> None:
    sid = int(call.data.split(":")[2])
    session = await db.get_session(sid)
    if not session or session["owner_id"] != call.from_user.id:
        await call.answer("Bu testni faqat boshlagan odam to'xtata oladi.", show_alert=True)
        return
    cancel_runner(sid)
    await db.finish_session(sid, "aborted")
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("⏹ Test to'xtatildi.",
                              reply_markup=ui.menu_for(call.message.chat))
    await call.answer()
