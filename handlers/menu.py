"""Bosh menyu, yordam, statistika."""
from __future__ import annotations

from aiogram import F, Router, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext

import db
import ui

router = Router(name="menu")

WELCOME = (
    "👋 <b>Assalomu alaykum, {name}!</b>\n\n"
    "Bu — ikki rejimli test boti.\n\n"
    "🎯 <b>Klassik rejim</b> — Telegram'ning o'z QuizBot uslubi: savollar "
    "jonli so'rovnoma (quiz poll) ko'rinishida, taymer bilan keladi. "
    "Guruhga qo'shsangiz — barcha a'zolar birga yechadi, oxirida reyting chiqadi.\n\n"
    "🧠 <b>Pro rejim</b> — zamonaviy interfeys: bitta xabar ichida navigatsiya, "
    "progress-bar, 50:50 yordami, «o'rgandim» belgisi, xatolar tahlili.\n\n"
    "👥 <b>Guruhda</b> ikkala rejim ham jamoaviy ishlaydi: botni guruhga qo'shib "
    "<code>/quiz</code> yoki <code>/pro</code> yozing — qatnashchilar yig'iladi, "
    "hamma birga yechadi, oxirida umumiy reyting chiqadi.\n"
    "🧩 <b>IQ test</b> — vaqt cheklangan mantiqiy test: ketma-ketliklar, analogiya, "
    "mantiqiy masalalar. Qiyin savol ko'proq ball keltiradi, oxirida bo'limlar "
    "bo'yicha tahlil chiqadi.\n\n"
    "🔐 Har kim <b>o'z bazasini</b> yaratadi: savollaringizni faqat siz ko'rasiz, "
    "xohlasangiz tanlagan guruhingizga yoki hammaga ochasiz.\n"
    "➕ Savollarni <b>JSON</b> yoki <b>Word (.docx)</b> fayl orqali qo'shasiz.\n\n"
    "Quyidagi tugmalardan birini tanlang 👇"
)

HELP = (
    "📖 <b>Qo'llanma</b>\n\n"
    "<b>Rejimlar</b>\n"
    "🎯 <i>Klassik</i> — Telegram quiz-poll. Shaxsiy chatda javob bergach "
    "keyingi savol darhol keladi; guruhda taymer tugagach o'tadi.\n"
    "🧠 <i>Pro</i> — bitta xabar, tugmalar bilan boshqariladi. Savollar orasida "
    "erkin yurish, 50:50, belgilash va yakunda to'liq tahlil.\n\n"
    "<b>🔐 Kim nimani ko'radi</b>\n"
    "Siz qo'shgan savollar <b>sukut bo'yicha faqat sizniki</b>. «📚 Bazalar» → "
    "bazani tanlang → «🔐 Kim ko'ra oladi?»:\n"
    "🔒 <i>Faqat men</i> · 👥 <i>Tanlangan guruhlar</i> · 🌍 <i>Hamma</i>\n"
    "Guruh ro'yxatda chiqishi uchun botni o'sha guruhga qo'shib, u yerda bir marta "
    "<code>/start</code> yozing.\n\n"
    "<b>Savol qo'shish</b>\n"
    "➕ tugmasini bosing va fayl yuboring.\n\n"
    "<code>JSON</code> — quyidagi shakllardan istalgani:\n"
    "<pre>[{\"question\":\"Savol?\",\n"
    "  \"options\":[\"A\",\"B\",\"C\"],\n"
    "  \"answer\":0}]</pre>\n"
    "<pre>[{\"q\":\"Savol?\",\"c\":\"to'g'ri\",\n"
    "  \"a\":[\"xato\",\"xato\"]}]</pre>\n\n"
    "<code>Word (.docx)</code> — taniladigan ko'rinishlar:\n"
    "<pre>1. Savol matni?\n"
    "+To'g'ri javob\n"
    "-Xato\n"
    "-Xato</pre>\n"
    "<pre>1. Savol matni?\n"
    "A) birinchi\n"
    "B) ikkinchi\n"
    "Javob: B</pre>\n"
    "Belgisiz jadval/«====» formati ham o'qiladi — u holda birinchi variant "
    "to'g'ri deb olinadi va bot bu haqda ogohlantiradi.\n\n"
    "<b>👥 Guruhda</b>\n"
    "Botni guruhga qo'shing va <code>/quiz</code> (klassik) yoki <code>/pro</code> "
    "(jang) yozing. Lobbi ochiladi: «✅ Qatnashaman» bosgan hamma ro'yxatga tushadi, "
    "tashkilotchi savollar soni/vaqtini sozlab «▶️ Boshlash» bosadi.\n"
    "Pro jangda hamma bir vaqtda javob beradi — <b>tez javob ko'proq ball</b> keltiradi.\n"
    "<code>/reyting</code> — guruhning umumiy reytingi.\n\n"
    "<b>Buyruqlar</b>\n"
    "/start — bosh menyu\n"
    "/quiz — klassik rejim\n"
    "/pro — pro rejim\n"
    "/iq — IQ test\n"
    "/stop — joriy testni to'xtatish\n"
    "/stats — statistika\n"
    "/bazalar — bazalar ro'yxati"
)


@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    user = message.from_user
    await db.touch_user(user.id, user.full_name, user.username)
    await db.get_prefs(user.id)
    await message.answer(
        WELCOME.format(name=ui.esc(user.first_name or "do'stim")),
        reply_markup=ui.menu_for(message.chat),
    )
    me = await message.bot.me()
    await message.answer(
        "👥 Do'stlaringiz bilan birga o'ynash uchun botni guruhga qo'shing:",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[
            types.InlineKeyboardButton(
                text="➕ Guruhga qo'shish",
                url=f"https://t.me/{me.username}?startgroup=quiz")]]))


@router.message(Command("help"))
@router.message(F.text == ui.BTN_HELP)
async def cmd_help(message: types.Message) -> None:
    await message.answer(HELP, reply_markup=ui.menu_for(message.chat))


@router.message(Command("stop"))
async def cmd_stop(message: types.Message, state: FSMContext) -> None:
    from handlers import classic
    await state.clear()
    session = await db.active_session(message.from_user.id)
    await db.abort_active(message.from_user.id)
    if session:
        classic.cancel_runner(session["id"])
        await message.answer("⏹ Joriy test to'xtatildi.", reply_markup=ui.menu_for(message.chat))
    else:
        await message.answer("Hozir faol test yo'q.", reply_markup=ui.menu_for(message.chat))


@router.message(Command("stats"))
@router.message(F.text == ui.BTN_STATS)
async def cmd_stats(message: types.Message) -> None:
    uid = message.from_user.id
    st = await db.user_stats(uid)
    pct = (st["correct"] / st["answers"] * 100) if st["answers"] else 0
    name, emoji = ui.grade(pct)
    lines = [
        "📊 <b>Sizning statistikangiz</b>\n",
        f"🧩 Yakunlangan testlar: <b>{st['sessions']}</b>",
        f"✍️ Berilgan javoblar: <b>{st['answers']}</b>",
        f"✅ To'g'ri: <b>{st['correct']}</b>   ❌ Xato: <b>{st['answers'] - st['correct']}</b>",
        f"🎯 Aniqlik: <b>{pct:.1f}%</b>  {emoji} {name}",
        f"🎓 «O'rgandim» belgilangan: <b>{st['learned']}</b>",
    ]
    top = await db.global_top(10)
    if top:
        lines.append("\n🏅 <b>Umumiy reyting</b> (≥10 javob)")
        for i, r in enumerate(top, 1):
            acc = r["correct"] / r["total"] * 100
            mark = " ← siz" if r["user_id"] == uid else ""
            lines.append(
                f"{ui.medal(i)} {ui.esc(r['name'] or 'Foydalanuvchi')} — "
                f"{acc:.0f}% ({r['correct']}/{r['total']}){mark}")
    await message.answer("\n".join(lines), reply_markup=ui.menu_for(message.chat))
