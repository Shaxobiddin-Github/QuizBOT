"""Guruh rejimi: lobbi + ikkala rejimda jamoaviy o'yin."""
from __future__ import annotations

import asyncio
import contextlib
import time

from aiogram import Bot, F, Router, types
from aiogram.exceptions import (TelegramAPIError, TelegramBadRequest,
                                TelegramRetryAfter)
from aiogram.filters import Command

import bg
import config
import db
import media
import ui

router = Router(name="group")

GROUP = F.chat.type.in_({"group", "supergroup"})

# chat_id -> lobbi ma'lumoti
LOBBIES: dict[int, dict] = {}
# chat_id -> ishlayotgan o'yin (session_id, task)
GAMES: dict[int, dict] = {}
# (session_id, q_index) -> jonli savol konteksti (pro jang)
BATTLE: dict[tuple[int, int], dict] = {}

MODE_NAME = {"classic": "🎯 Klassik (quiz-poll)", "battle": "🧠 Pro jang"}

# Telegram bitta chatda tez-tez tahrirlashga yo'l qo'ymaydi (flood control).
# Ko'p kishi birdan tugma bossa, tahrirlarni bitta yangilanishga yig'amiz.
EDIT_GAP = 2.5
_pending_refresh: dict[int, asyncio.Task] = {}


async def _safe_edit(bot: Bot, chat_id: int, msg_id: int, text: str,
                     markup=None) -> bool:
    """Xabarni tahrirlaydi; flood-limitga urilsa kutib bir marta qayta uradi."""
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id,
                                    reply_markup=markup)
        return True
    except TelegramRetryAfter as exc:
        await asyncio.sleep(exc.retry_after + 1)
        with contextlib.suppress(TelegramAPIError):
            await bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id,
                                        reply_markup=markup)
        return True
    except TelegramAPIError:
        return False


# ------------------------------------------------------------------ yordamchi
async def _is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    with contextlib.suppress(Exception):
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("creator", "administrator")
    return False


async def _can_manage(call: types.CallbackQuery, lobby: dict) -> bool:
    if call.from_user.id == lobby["owner_id"]:
        return True
    return await _is_admin(call.bot, call.message.chat.id, call.from_user.id)


def points_of(correct: bool, spent_ms: int, timer: int) -> int:
    if not correct:
        return 0
    left = max(0.0, 1 - (spent_ms / 1000) / max(timer, 1))
    return 100 + int(50 * left)


# --------------------------------------------------------------------- lobbi
async def open_lobby(message: types.Message, mode: str) -> None:
    chat_id = message.chat.id
    if chat_id in GAMES:
        await message.answer("⏳ Bu guruhda test allaqachon ketmoqda. To'xtatish: /stop")
        return

    allowed = [c for c in await db.collections_for_chat(chat_id) if c["n"]]
    if not allowed:
        await message.answer(
            "📚 <b>Bu guruhga ochilgan baza yo'q.</b>\n\n"
            "Baza egasi botga yakka chatda yozib: «📚 Bazalar» → bazani tanlab → "
            "«🔐 Kim ko'ra oladi?» → «👥 Guruhlar» → shu guruhni belgilashi kerak.\n\n"
            "<i>Guruh ro'yxatda chiqishi uchun avval shu yerda /start yozing.</i>")
        return
    prefs = await db.get_prefs(message.from_user.id)
    col_id = prefs["collection_id"]
    if col_id not in {c["id"] for c in allowed}:
        col_id = allowed[0]["id"]

    LOBBIES[chat_id] = {
        "mode": mode,
        "owner_id": message.from_user.id,
        "owner_name": message.from_user.full_name,
        "col_id": col_id,
        # 0 — «barchasi»; None bo'lsa standart 10 ta
        "count": prefs["count"] if prefs["count"] is not None else 10,
        "timer": prefs["timer"] or 20,
        "players": {},
        "msg_id": None,
    }
    card = await _lobby_card(chat_id)
    if card is None:
        return
    text, markup = card
    sent = await message.answer(text, reply_markup=markup)
    if chat_id in LOBBIES:
        LOBBIES[chat_id]["msg_id"] = sent.message_id


async def _lobby_card(chat_id: int) -> tuple[str, types.InlineKeyboardMarkup] | None:
    lobby = LOBBIES.get(chat_id)
    if lobby is None:          # o'yin boshlanib ketgan yoki bekor qilingan
        return None
    col = await db.collection(lobby["col_id"])
    total = await db.count_questions(lobby["col_id"])
    count = min(lobby["count"], total) if lobby["count"] > 0 else total

    players = lobby["players"]
    names = ", ".join(ui.esc(n) for n in list(players.values())[:20]) or "<i>hali yo'q</i>"

    text = (
        f"🎮 <b>Guruh testi</b> — {MODE_NAME[lobby['mode']]}\n\n"
        f"📚 Baza: <b>{ui.esc(col['title'])}</b>\n"
        f"🔢 Savollar: <b>{count}</b> ta   ·   ⏱ Har biriga: <b>{lobby['timer']} s</b>\n"
        f"👤 Tashkilotchi: {ui.esc(lobby['owner_name'])}\n\n"
        f"👥 <b>Qatnashchilar ({len(players)}):</b> {names}\n\n"
        + ("<i>🧠 Pro jangda hamma bir vaqtda javob beradi — tez javob "
           "bergan ko'proq ball oladi.</i>" if lobby["mode"] == "battle" else
           "<i>🎯 Savollar quiz-so'rovnoma bo'lib keladi, hamma javob bera oladi.</i>")
    )
    rows = [
        [("✅ Qatnashaman", "g:join")],
        [("🔢 Soni", "g:cnt"), ("⏱ Vaqt", "g:tmr"), ("📚 Baza", "g:col")],
        [("🔀 Rejimni almashtirish", "g:mode")],
        [("▶️ Boshlash", "g:go"), ("❌ Bekor", "g:cancel")],
    ]
    return text, ui.kb(rows)


async def _delayed_refresh(bot: Bot, chat_id: int, msg_id: int, delay: float) -> None:
    await asyncio.sleep(delay)
    _pending_refresh.pop(chat_id, None)
    card = await _lobby_card(chat_id)
    if card is None:
        return
    text, markup = card
    await _safe_edit(bot, chat_id, msg_id, text, markup)


async def _refresh_lobby(call: types.CallbackQuery, immediate: bool = False) -> bool:
    """Lobbi kartasini yangilaydi. Lobbi yopilgan bo'lsa False qaytaradi.

    `immediate=False` — yangilanish EDIT_GAP soniyaga kechiktiriladi va shu
    oraliqdagi barcha bosishlar bitta tahrirga yig'iladi (flood controldan
    qochish uchun: guruhda o'nlab odam birdan «Qatnashaman» bosishi mumkin).
    """
    chat_id = call.message.chat.id
    if LOBBIES.get(chat_id) is None:
        with contextlib.suppress(TelegramAPIError):
            await call.message.edit_reply_markup(reply_markup=None)
        return False

    if immediate:
        card = await _lobby_card(chat_id)
        if card is None:
            return False
        text, markup = card
        await _safe_edit(call.bot, chat_id, call.message.message_id, text, markup)
        return True

    task = _pending_refresh.get(chat_id)
    if task is None or task.done():
        _pending_refresh[chat_id] = bg.spawn(
            _delayed_refresh(call.bot, chat_id, call.message.message_id, EDIT_GAP))
    return True


@router.my_chat_member(GROUP)
async def on_bot_added(event: types.ChatMemberUpdated) -> None:
    """Bot guruhga qo'shilganda guruhni ro'yxatga olamiz."""
    chat = event.chat
    await db.touch_chat(chat.id, chat.title or "", chat.type)
    if event.from_user and not event.from_user.is_bot:
        await db.touch_chat_member(chat.id, event.from_user.id)
    new = event.new_chat_member
    if new.user.id != (await event.bot.me()).id:
        return
    if new.status in ("member", "administrator"):
        await event.bot.send_message(
            chat.id,
            "👋 <b>Salom!</b> Test boti guruhga qo'shildi.\n\n"
            "🎯 /quiz — klassik test\n"
            "🧠 /pro — Pro jang\n"
            "🏆 /reyting — guruh reytingi\n\n"
            "📚 O'z savollaringizni shu guruhga ochish uchun botga yakka chatda: "
            "«📚 Bazalar» → baza → «🔐 Kim ko'ra oladi?» → «👥 Guruhlar» → "
            f"«{ui.esc(chat.title or 'shu guruh')}» ni belgilang.")


@router.message(Command("quiz"), GROUP)
async def cmd_group_classic(message: types.Message) -> None:
    await db.touch_user(message.from_user.id, message.from_user.full_name,
                        message.from_user.username)
    await open_lobby(message, "classic")


@router.message(Command("pro", "jang", "battle"), GROUP)
async def cmd_group_battle(message: types.Message) -> None:
    await db.touch_user(message.from_user.id, message.from_user.full_name,
                        message.from_user.username)
    await open_lobby(message, "battle")


@router.message(Command("start"), GROUP)
async def cmd_group_start(message: types.Message) -> None:
    await message.answer(
        "👋 <b>Guruh test boti</b>\n\n"
        "🎯 /quiz — klassik test (quiz-so'rovnomalar)\n"
        "🧠 /pro — Pro jang (hamma bir vaqtda javob beradi, tezlik uchun bonus ball)\n"
        "⏹ /stop — o'yinni to'xtatish\n\n"
        "Savol qo'shish va shaxsiy mashq uchun botga yakka chatda yozing.",
        reply_markup=ui.kb([[("🎯 Klassik", "g:new:classic"),
                             ("🧠 Pro jang", "g:new:battle")]]))


@router.callback_query(F.data.startswith("g:new:"))
async def cb_new(call: types.CallbackQuery) -> None:
    await db.touch_user(call.from_user.id, call.from_user.full_name,
                        call.from_user.username)
    await open_lobby(call.message, call.data.split(":")[2])
    await call.answer()


@router.callback_query(F.data == "g:join")
async def cb_join(call: types.CallbackQuery) -> None:
    lobby = LOBBIES.get(call.message.chat.id)
    if not lobby:
        await call.answer("Bu lobbi yopilgan.", show_alert=True)
        return
    uid = call.from_user.id
    if uid in lobby["players"]:
        del lobby["players"][uid]
        await call.answer("Ro'yxatdan chiqdingiz.")
    else:
        lobby["players"][uid] = call.from_user.first_name or call.from_user.full_name
        await db.touch_user(uid, call.from_user.full_name, call.from_user.username)
        await call.answer("✅ Siz qatnashchilar ro'yxatidasiz!")
    if not await _refresh_lobby(call):
        with contextlib.suppress(TelegramBadRequest):
            await call.answer("O'yin allaqachon boshlandi — savollarga javob bering!",
                              show_alert=True)


@router.callback_query(F.data == "g:mode")
async def cb_mode(call: types.CallbackQuery) -> None:
    lobby = LOBBIES.get(call.message.chat.id)
    if not lobby:
        await call.answer("Lobbi yopilgan.", show_alert=True)
        return
    if not await _can_manage(call, lobby):
        await call.answer("Faqat tashkilotchi yoki admin o'zgartira oladi.", show_alert=True)
        return
    lobby["mode"] = "battle" if lobby["mode"] == "classic" else "classic"
    await _refresh_lobby(call, immediate=True)
    await call.answer(MODE_NAME[lobby["mode"]])


@router.callback_query(F.data.in_({"g:cnt", "g:tmr", "g:col"}))
async def cb_params(call: types.CallbackQuery) -> None:
    lobby = LOBBIES.get(call.message.chat.id)
    if not lobby:
        await call.answer("Lobbi yopilgan.", show_alert=True)
        return
    if not await _can_manage(call, lobby):
        await call.answer("Faqat tashkilotchi yoki admin o'zgartira oladi.", show_alert=True)
        return

    what = call.data.split(":")[1]
    if what == "cnt":
        total = await db.count_questions(lobby["col_id"])
        values = [c for c in (5, 10, 15, 20, 30, 50) if c < total] + [0]
        rows, cur = [], []
        for v in values:
            cur.append((f"Barchasi ({total})" if v == 0 else str(v), f"g:set:cnt:{v}"))
            if len(cur) == 3:
                rows.append(cur)
                cur = []
        if cur:
            rows.append(cur)
        title = "🔢 Nechta savol bo'lsin?"
    elif what == "tmr":
        rows, cur = [], []
        for v in config.TIMER_CHOICES:
            cur.append((f"{v} s", f"g:set:tmr:{v}"))
            if len(cur) == 3:
                rows.append(cur)
                cur = []
        if cur:
            rows.append(cur)
        title = "⏱ Har savolga qancha vaqt?"
    else:
        cols = [c for c in await db.collections_for_chat(call.message.chat.id) if c["n"]]
        rows = [[(f"{ui.shorten(c['title'], 28)} · {c['n']}", f"g:set:col:{c['id']}")]
                for c in cols]
        title = ("📚 Bu guruhga ochilgan bazalar:" if cols else
                 "📚 Bu guruhga hech qanday baza ochilmagan.")
    rows.append([("⬅️ Orqaga", "g:back")])
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(title, reply_markup=ui.kb(rows))
    await call.answer()


@router.callback_query(F.data.startswith("g:set:"))
async def cb_set(call: types.CallbackQuery) -> None:
    lobby = LOBBIES.get(call.message.chat.id)
    if not lobby:
        await call.answer("Lobbi yopilgan.", show_alert=True)
        return
    _, _, what, value = call.data.split(":")
    if what == "col":
        allowed = {c["id"] for c in await db.collections_for_chat(call.message.chat.id)}
        if int(value) not in allowed:
            await call.answer("Bu baza guruhga ochilmagan.", show_alert=True)
            return
    key = {"cnt": "count", "tmr": "timer", "col": "col_id"}[what]
    lobby[key] = int(value)
    await _refresh_lobby(call, immediate=True)
    await call.answer("Saqlandi ✅")


@router.callback_query(F.data == "g:back")
async def cb_back(call: types.CallbackQuery) -> None:
    if call.message.chat.id not in LOBBIES:
        await call.answer("Lobbi yopilgan.", show_alert=True)
        return
    await _refresh_lobby(call, immediate=True)
    await call.answer()


@router.callback_query(F.data == "g:cancel")
async def cb_cancel(call: types.CallbackQuery) -> None:
    lobby = LOBBIES.get(call.message.chat.id)
    if not lobby:
        await call.answer()
        return
    if not await _can_manage(call, lobby):
        await call.answer("Faqat tashkilotchi bekor qila oladi.", show_alert=True)
        return
    LOBBIES.pop(call.message.chat.id, None)
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text("❌ Guruh testi bekor qilindi.")
    await call.answer()


@router.callback_query(F.data == "g:go")
async def cb_go(call: types.CallbackQuery) -> None:
    chat_id = call.message.chat.id
    lobby = LOBBIES.get(chat_id)
    if not lobby:
        await call.answer("Lobbi yopilgan.", show_alert=True)
        return
    if not await _can_manage(call, lobby):
        await call.answer("Boshlashni faqat tashkilotchi yoki admin bosadi.",
                          show_alert=True)
        return
    if chat_id in GAMES:
        await call.answer("O'yin allaqachon ketmoqda.", show_alert=True)
        return
    await call.answer("Boshlandi!")
    LOBBIES.pop(chat_id, None)
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_reply_markup(reply_markup=None)
    await launch(call.bot, chat_id, lobby)


# ------------------------------------------------------------------- ishga tushirish
async def launch(bot: Bot, chat_id: int, lobby: dict) -> None:
    col_id = lobby["col_id"]
    q_ids = await db.pick_questions(col_id, lobby["count"], shuffle=True)
    if not q_ids:
        await bot.send_message(chat_id, "Savol topilmadi.")
        return

    questions = await db.questions_by_ids(q_ids)
    q_ids = [q for q in q_ids if q in questions]
    perm = [db.make_perm(questions[qid]) for qid in q_ids]

    settings = {"timer": lobby["timer"], "shuffle_a": 1, "perm": perm,
                "players": lobby["players"], "group": 1}
    mode = "battle" if lobby["mode"] == "battle" else "classic"
    sid = await db.create_session(lobby["owner_id"], chat_id, col_id, mode, q_ids, settings)

    col = await db.collection(col_id)
    await bot.send_message(
        chat_id,
        f"🚦 <b>Boshlandi!</b>\n\n"
        f"{MODE_NAME[lobby['mode']]}\n"
        f"📚 {ui.esc(col['title'])}\n"
        f"🔢 {len(q_ids)} ta savol · ⏱ {lobby['timer']} s\n"
        f"👥 Ro'yxatdagi qatnashchilar: {len(lobby['players'])}\n\n"
        f"<i>To'xtatish: /stop</i>")
    await asyncio.sleep(2)

    if mode == "classic":
        from handlers import classic
        task = asyncio.create_task(classic._run(bot, sid, True))
    else:
        task = asyncio.create_task(_run_battle(bot, chat_id, sid))
    GAMES[chat_id] = {"sid": sid, "task": task}
    task.add_done_callback(lambda _t, c=chat_id: GAMES.pop(c, None))


async def stop_game(bot: Bot, chat_id: int) -> bool:
    game = GAMES.pop(chat_id, None)
    LOBBIES.pop(chat_id, None)
    if not game:
        return False
    if not game["task"].done():
        game["task"].cancel()
    from handlers import classic
    classic.cancel_runner(game["sid"])
    await db.finish_session(game["sid"], "aborted")
    for key in [k for k in BATTLE if k[0] == game["sid"]]:
        BATTLE.pop(key, None)
    return True


# ------------------------------------------------------------------ Pro jang
async def _run_battle(bot: Bot, chat_id: int, sid: int) -> None:
    try:
        session = await db.get_session(sid)
        q_ids = session["q_ids"]
        perm = session["settings"]["perm"]
        timer = int(session["settings"]["timer"])
        players = {int(k): v for k, v in session["settings"]["players"].items()}
        questions = await db.questions_by_ids(q_ids)
        total = len(q_ids)

        for index, qid in enumerate(q_ids):
            fresh = await db.get_session(sid)
            if not fresh or fresh["status"] != "active":
                return
            q = questions[qid]
            order = perm[index]
            shown = [q["options"][i] for i in order]
            correct = order.index(q["correct"])

            ctx = {
                "sid": sid, "index": index, "total": total, "qid": q["id"],
                "chat_id": chat_id, "text": q["text"], "shown": shown,
                "correct": correct, "explanation": q["explanation"],
                "timer": timer, "registered": players,
                "names": dict(players), "answers": {},
                "start": time.monotonic(), "event": asyncio.Event(),
                "last_edit": 0.0, "msg_id": None, "q": q, "photo": False,
            }
            photo = await media.photo_for(bot, q)
            msg = await media.send(bot, chat_id, _battle_card(ctx), _battle_kb(ctx), photo)
            ctx["msg_id"] = msg.message_id
            ctx["photo"] = bool(getattr(msg, "photo", None))
            ctx["start"] = time.monotonic()          # rasm yuklanishi vaqtga qo'shilmasin
            BATTLE[(sid, index)] = ctx

            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(ctx["event"].wait(), timeout=timer)

            BATTLE.pop((sid, index), None)
            await media.edit_card(bot, chat_id, ctx["msg_id"], ctx["photo"],
                                  _battle_card(ctx, revealed=True))
            await db.set_cursor(sid, index + 1)
            if index < total - 1:
                await asyncio.sleep(3)

        await db.finish_session(sid)
        await _battle_results(bot, chat_id, sid, timer, total)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # pragma: no cover
        with contextlib.suppress(Exception):
            await bot.send_message(chat_id, f"⚠️ Xatolik: <code>{ui.esc(exc)}</code>")
        await db.finish_session(sid, "error")
    finally:
        for key in [k for k in BATTLE if k[0] == sid]:
            BATTLE.pop(key, None)


def _battle_card(ctx: dict, revealed: bool = False) -> str:
    head = (f"🧠 <b>Pro jang</b>  ·  savol <b>{ctx['index'] + 1}/{ctx['total']}</b>"
            f"  ·  ⏱ {ctx['timer']} s\n")
    q = ctx.get("q") or {}
    img_opts = media.has_option_images(q)
    limit = 500 if media.has_media(q) else 3000
    body = f"\n<b>{ui.esc(ui.shorten(ctx['text'], limit))}</b>\n\n"
    right = (ui.LETTERS[ctx["correct"]] if img_opts else
             f"{ui.LETTERS[ctx['correct']]}) {ui.esc(ui.shorten(ctx['shown'][ctx['correct']], 200))}")
    if revealed:
        if not img_opts:
            body += ui.render_options(ctx["shown"], correct=ctx["correct"], reveal=True)
        good, bad = [], []
        for uid, (opt, _spent) in ctx["answers"].items():
            name = ctx["names"].get(uid, "?")
            (good if opt == ctx["correct"] else bad).append(name)
        body += f"\n\n✅ <b>To'g'ri javob:</b> {right}"
        if ctx["explanation"]:
            body += f"\n💡 <i>{ui.esc(ui.shorten(ctx['explanation'], 250))}</i>"
        body += f"\n\n👥 Javob berganlar: <b>{len(ctx['answers'])}</b>"
        if good:
            body += f"\n🎯 Topganlar: {', '.join(ui.esc(n) for n in good[:15])}"
        if bad:
            body += f"\n❌ Adashganlar: {', '.join(ui.esc(n) for n in bad[:15])}"
    else:
        body += ("<i>🖼 Javob variantlari rasmda</i>" if img_opts
                 else ui.render_options(ctx["shown"]))
        body += (f"\n\n👥 Javob berganlar: <b>{len(ctx['answers'])}</b>"
                 + (f"/{len(ctx['registered'])}" if ctx["registered"] else "")
                 + "\n<i>Javobni tanlang — kim tez javob bersa, ko'proq ball oladi.</i>")
    return head + body


def _battle_kb(ctx: dict) -> types.InlineKeyboardMarkup:
    letters = [(ui.LETTERS[i], f"gb:{ctx['sid']}:{ctx['index']}:{i}")
               for i in range(len(ctx["shown"]))]
    rows = [letters[i:i + 4] for i in range(0, len(letters), 4)]
    return ui.kb(rows)


@router.callback_query(F.data.startswith("gb:"))
async def cb_battle_answer(call: types.CallbackQuery) -> None:
    _, sid, index, opt = call.data.split(":")
    ctx = BATTLE.get((int(sid), int(index)))
    if ctx is None:
        await call.answer("⏰ Bu savol vaqti tugagan.", show_alert=True)
        return
    uid = call.from_user.id
    if uid in ctx["answers"]:
        await call.answer("Siz allaqachon javob berdingiz 🙂", show_alert=True)
        return

    opt = int(opt)
    if not 0 <= opt < len(ctx["shown"]):
        await call.answer()
        return
    spent = int((time.monotonic() - ctx["start"]) * 1000)
    name = call.from_user.first_name or call.from_user.full_name
    ctx["names"].setdefault(uid, name)
    ctx["answers"][uid] = (opt, spent)

    await db.touch_user(uid, call.from_user.full_name, call.from_user.username)
    await db.save_answer(ctx["sid"], uid, name, ctx["index"], ctx["qid"],
                         opt, opt == ctx["correct"], spent)
    await call.answer(f"✅ Javobingiz qabul qilindi: {ui.LETTERS[opt]}")

    registered = set(ctx["registered"])
    if registered and registered.issubset(set(ctx["answers"])):
        ctx["event"].set()
        return

    now = time.monotonic()
    if now - ctx["last_edit"] > EDIT_GAP:
        ctx["last_edit"] = now
        await media.edit_card(call.bot, ctx["chat_id"], ctx["msg_id"], ctx["photo"],
                              _battle_card(ctx), _battle_kb(ctx))


async def _battle_results(bot: Bot, chat_id: int, sid: int, timer: int,
                          total: int) -> None:
    rows = await db.session_answers(sid)
    if not rows:
        await bot.send_message(chat_id, "🏁 O'yin tugadi — hech kim javob bermadi.")
        return

    table: dict[int, dict] = {}
    for r in rows:
        rec = table.setdefault(r["user_id"], {
            "name": r["user_name"], "correct": 0, "answered": 0, "points": 0, "ms": 0})
        rec["answered"] += 1
        rec["ms"] += r["spent_ms"]
        if r["is_correct"]:
            rec["correct"] += 1
        rec["points"] += points_of(bool(r["is_correct"]), r["spent_ms"], timer)

    board = sorted(table.values(), key=lambda x: (-x["points"], x["ms"]))
    lines = ["🏁 <b>Pro jang yakunlandi!</b>",
             f"📋 {total} ta savol · 👥 {len(board)} ishtirokchi\n",
             "🏆 <b>Yakuniy reyting</b>"]
    for i, r in enumerate(board, 1):
        lines.append(
            f"{ui.medal(i)} <b>{ui.esc(r['name'])}</b> — {r['points']} ball  "
            f"(✅ {r['correct']}/{total} · {r['ms'] / 1000:.0f}s)")
    if board:
        lines.append(f"\n👑 G'olib: <b>{ui.esc(board[0]['name'])}</b>!")
    await bot.send_message(chat_id, "\n".join(lines), reply_markup=ui.kb([
        [("🎯 Klassik", "g:new:classic"), ("🧠 Yana jang", "g:new:battle")]]))


@router.message(Command("reyting", "top"), GROUP)
async def cmd_group_top(message: types.Message) -> None:
    board = await db.chat_leaderboard(message.chat.id)
    if not board:
        await message.answer("Bu guruhda hali test o'ynalmagan. /quiz yoki /pro")
        return
    lines = [f"🏆 <b>{ui.esc(message.chat.title or 'Guruh')} reytingi</b>\n"]
    for i, r in enumerate(board, 1):
        acc = r["correct"] / r["total"] * 100 if r["total"] else 0
        lines.append(
            f"{ui.medal(i)} <b>{ui.esc(r['name'] or 'Foydalanuvchi')}</b> — "
            f"{r['correct']}/{r['total']} ({acc:.0f}%) · {r['games']} ta test")
    await message.answer("\n".join(lines))


# ----------------------------------------------------------------------- stop
@router.message(Command("stop"), GROUP)
async def cmd_group_stop(message: types.Message) -> None:
    chat_id = message.chat.id
    game = GAMES.get(chat_id)
    lobby = LOBBIES.get(chat_id)
    owner = None
    if game:
        session = await db.get_session(game["sid"])
        owner = session["owner_id"] if session else None
    if owner is None and lobby:
        owner = lobby["owner_id"]
    if owner is not None and message.from_user.id != owner and \
            not await _is_admin(message.bot, chat_id, message.from_user.id):
        await message.answer("To'xtatishni tashkilotchi yoki admin bajaradi.")
        return
    if await stop_game(message.bot, chat_id):
        await message.answer("⏹ O'yin to'xtatildi.")
    elif lobby:
        LOBBIES.pop(chat_id, None)
        await message.answer("⏹ Lobbi yopildi.")
    else:
        await message.answer("Bu guruhda faol o'yin yo'q.")
