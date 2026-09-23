"""Umumiy matn/klaviatura yordamchilari."""
from __future__ import annotations

import html

from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, ReplyKeyboardMarkup)

LETTERS = "ABCDEFGHIJ"
BTN_CLASSIC = "🎯 Klassik rejim"
BTN_PRO = "🧠 Pro rejim"
BTN_IQ = "🧩 IQ test"
BTN_LIB = "📚 Bazalar"
BTN_ADD = "➕ Savol qo'shish"
BTN_STATS = "📊 Statistika"
BTN_SETTINGS = "⚙️ Sozlamalar"
BTN_HELP = "❓ Yordam"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CLASSIC), KeyboardButton(text=BTN_PRO)],
            [KeyboardButton(text=BTN_IQ), KeyboardButton(text=BTN_LIB)],
            [KeyboardButton(text=BTN_ADD), KeyboardButton(text=BTN_STATS)],
            [KeyboardButton(text=BTN_SETTINGS), KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Rejimni tanlang…",
    )


def menu_for(chat) -> ReplyKeyboardMarkup | None:
    """Reply-klaviatura faqat shaxsiy chatda ko'rsatiladi."""
    return main_menu() if getattr(chat, "type", "private") == "private" else None


def esc(text: str) -> str:
    return html.escape(str(text), quote=False)


def kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    """[[(matn, callback_data), …], …] -> InlineKeyboardMarkup."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows
    ])


def progress_bar(done: int, total: int, width: int = 10) -> str:
    total = max(total, 1)
    filled = round(width * done / total)
    return "▰" * filled + "▱" * (width - filled)


def fmt_time(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def grade(percent: float) -> tuple[str, str]:
    """Foizga qarab baho va emoji."""
    if percent >= 90:
        return "A'lo", "🏆"
    if percent >= 75:
        return "Yaxshi", "🥇"
    if percent >= 60:
        return "Qoniqarli", "🥈"
    if percent >= 40:
        return "Qoniqarsiz", "🥉"
    return "Yomon", "📉"


def medal(place: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(place, f"{place}.")


def shorten(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def render_options(options: list[str], chosen: int | None = None,
                   correct: int | None = None, reveal: bool = False,
                   hidden: set[int] | None = None) -> str:
    hidden = hidden or set()
    lines = []
    for i, opt in enumerate(options):
        letter = LETTERS[i]
        if i in hidden:
            lines.append(f"<s>{letter}) {esc(opt)}</s>")
            continue
        mark = ""
        if reveal and correct is not None:
            if i == correct:
                mark = " ✅"
            elif i == chosen:
                mark = " ❌"
        elif chosen == i:
            mark = " 🔵"
        lines.append(f"<b>{letter})</b> {esc(opt)}{mark}")
    return "\n".join(lines)
