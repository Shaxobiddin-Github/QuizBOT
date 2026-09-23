"""Ikki rejimli Telegram test boti — ishga tushirish nuqtasi."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats

import config
import access
import db
import seed
from handlers import ROUTERS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger("quizbot")

COMMANDS = [
    BotCommand(command="start", description="Bosh menyu"),
    BotCommand(command="quiz", description="🎯 Klassik rejim (QuizBot)"),
    BotCommand(command="pro", description="🧠 Pro rejim"),
    BotCommand(command="iq", description="🧩 IQ test"),
    BotCommand(command="bazalar", description="📚 Bazalar"),
    BotCommand(command="qoshish", description="➕ Savol qo'shish"),
    BotCommand(command="stats", description="📊 Statistika"),
    BotCommand(command="stop", description="⏹ Testni to'xtatish"),
    BotCommand(command="help", description="❓ Yordam"),
    BotCommand(command="id", description="🆔 ID va admin holati"),
]


GROUP_COMMANDS = [
    BotCommand(command="quiz", description="🎯 Klassik guruh testi"),
    BotCommand(command="pro", description="🧠 Pro jang (jamoaviy)"),
    BotCommand(command="reyting", description="🏆 Guruh reytingi"),
    BotCommand(command="stop", description="⏹ O'yinni to'xtatish"),
]


async def main() -> None:
    bot = Bot(config.BOT_TOKEN,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(access.ChatTracker())
    for router in ROUTERS:
        dp.include_router(router)

    await db.connect()
    await seed.ensure_default()
    await seed.ensure_iq()

    me = await bot.get_me()
    log.info("Bot ishga tushdi: @%s (id=%s)", me.username, me.id)
    await bot.set_my_commands(COMMANDS)
    await bot.set_my_commands(GROUP_COMMANDS,
                              scope=BotCommandScopeAllGroupChats())
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("To'xtatildi.")
