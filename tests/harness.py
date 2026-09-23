"""Soxta Telegram API — haqiqiy handler'larni Telegram'siz ishlatish uchun."""
import io, itertools
from datetime import datetime, timezone
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import (SendMessage, EditMessageText, EditMessageReplyMarkup,
                             AnswerCallbackQuery, SendPoll, GetMe, SetMyCommands,
                             DeleteWebhook, GetChatMember, SendDocument)

NOW = datetime.now(timezone.utc)
_ids = itertools.count(1000)
_polls = itertools.count(5000)

OWNERS = {101}          # guruh egasi deb hisoblanadigan foydalanuvchilar
MEMBERS: dict = {}      # chat_id -> a'zolar to'plami (yo'q bo'lsa — hamma a'zo)

ME = types.User(id=8651732102, is_bot=True, first_name="quizbotuz",
                username="quizbot_uzbot_bot")


def user(uid, name):
    return types.User(id=uid, is_bot=False, first_name=name, full_name=name)


def chat(cid, kind="private", title=None):
    return types.Chat(id=cid, type=kind, title=title)


class FakeSession:
    """Bot.session o'rniga: chaqiruvlarni yozib boradi va mos obyekt qaytaradi."""

    def __init__(self):
        self.calls = []          # (method_name, method_obj, result)
        self.messages = {}       # message_id -> matn
        self.polls = {}          # poll_id -> SendPoll

    async def __call__(self, bot, method, timeout=None):
        name = type(method).__name__
        result = self._handle(bot, method, name)
        self.calls.append((name, method, result))
        return result

    async def close(self):
        pass

    def _msg(self, cid, text, markup=None, poll=None, bot=None):
        mid = next(_ids)
        self.messages[mid] = text
        msg = types.Message(
            message_id=mid, date=NOW, chat=chat(cid), from_user=ME,
            text=text if poll is None else None, poll=poll,
            reply_markup=markup if isinstance(markup, types.InlineKeyboardMarkup) else None,
        )
        return msg.as_(bot) if bot is not None else msg

    def _handle(self, bot, m, name):
        if name == "GetMe":
            return ME
        if name in ("SetMyCommands", "DeleteWebhook", "AnswerCallbackQuery",
                    "SetMyDescription", "Close"):
            return True
        if name == "SendMessage":
            return self._msg(m.chat_id, m.text, m.reply_markup, bot=bot)
        if name == "CopyMessage":
            return types.MessageId(message_id=next(_ids))
        if name == "SendDocument":
            return self._msg(m.chat_id, m.caption or "<document>", bot=bot)
        if name in ("EditMessageText",):
            self.messages[m.message_id] = m.text
            return types.Message(message_id=m.message_id, date=NOW,
                                 chat=chat(m.chat_id), from_user=ME, text=m.text,
                                 reply_markup=m.reply_markup).as_(bot)
        if name == "EditMessageReplyMarkup":
            return True
        if name == "SendPoll":
            pid = str(next(_polls))
            self.polls[pid] = m
            poll = types.Poll(
                id=pid, question=m.question,
                options=[types.PollOption(persistent_id=str(i), voter_count=0,
                                          text=o if isinstance(o, str) else o.text)
                         for i, o in enumerate(m.options)],
                total_voter_count=0, is_closed=False, is_anonymous=False,
                type="quiz", allows_multiple_answers=False,
                allows_revoting=False, members_only=False,
                correct_option_id=m.correct_option_id)
            return self._msg(m.chat_id, "[POLL] " + m.question, poll=poll, bot=bot)
        if name == "GetChatMember":
            allowed = MEMBERS.get(m.chat_id)
            if allowed is not None and m.user_id not in allowed:
                return types.ChatMemberLeft(user=user(m.user_id, "Chetdagi"),
                                            status="left")
            if m.user_id in OWNERS:
                return types.ChatMemberOwner(user=user(m.user_id, "Owner"),
                                             status="creator", is_anonymous=False)
            return types.ChatMemberMember(user=user(m.user_id, "A'zo"), status="member")
        return True


def make(dp_routers):
    import access
    session = FakeSession()
    bot = Bot("8651732102:TEST", default=DefaultBotProperties(parse_mode=ParseMode.HTML),
              session=session)
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(access.ChatTracker())
    for r in dp_routers:
        dp.include_router(r)
    return bot, dp, session


def upd_my_chat_member(c, u, status="member"):
    return types.Update(update_id=next(_ids), my_chat_member=types.ChatMemberUpdated(
        chat=c, from_user=u, date=NOW,
        old_chat_member=types.ChatMemberLeft(user=ME, status="left"),
        new_chat_member=types.ChatMemberMember(user=ME, status=status)))


def upd_message(text, u, c, mid=None, document=None):
    return types.Update(update_id=next(_ids), message=types.Message(
        message_id=mid or next(_ids), date=NOW, chat=c, from_user=u,
        text=text if document is None else None, document=document,
        entities=[types.MessageEntity(type="bot_command", offset=0,
                                      length=len(text.split()[0]))]
        if text and text.startswith("/") else None))


def upd_call(data, u, c, msg_id=None, msg_text="x"):
    msg = types.Message(message_id=msg_id or next(_ids), date=NOW, chat=c,
                        from_user=ME, text=msg_text)
    return types.Update(update_id=next(_ids), callback_query=types.CallbackQuery(
        id=str(next(_ids)), from_user=u, chat_instance="ci", data=data, message=msg))


def upd_poll_answer(poll_id, u, option_ids):
    return types.Update(update_id=next(_ids), poll_answer=types.PollAnswer(
        poll_id=poll_id, user=u, option_ids=option_ids,
        option_persistent_ids=[str(i) for i in option_ids]))
