"""To'liq integratsion test: haqiqiy handler'lar, soxta Telegram API."""
import asyncio, io, os, re, sys, json, traceback
sys.path.insert(0, "/home/shaxobiddin/BOTS/quizbot")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H
from aiogram import types

import db, seed
from handlers import ROUTERS
import handlers.classic as classic
import handlers.group as group

OK, FAIL = [], []
def check(name, cond, extra=""):
    (OK if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  → {extra}" if extra and not cond else ""))

def last_texts(s, n=1, kind="SendMessage"):
    out = [m.text for k, m, _ in s.calls if k == kind and getattr(m, "text", None)]
    return out[-n:]

def btns(s, kind="SendMessage"):
    for k, m, _ in reversed(s.calls):
        if k in (kind, "EditMessageText") and getattr(m, "reply_markup", None):
            mk = m.reply_markup
            if isinstance(mk, types.InlineKeyboardMarkup):
                return [b.callback_data for row in mk.inline_keyboard for b in row]
    return []


async def main():
    await db.connect(); await seed.ensure_default()
    bot, dp, S = H.make(ROUTERS)
    ali, vali, sardor = H.user(101, "Ali"), H.user(102, "Vali"), H.user(103, "Sardor")
    priv, grp = H.chat(101), H.chat(-1001, "supergroup", "Test guruh")

    print("\n━━━ 1. SHAXSIY CHAT: /start, menyu ━━━")
    await dp.feed_update(bot, H.upd_message("/start", ali, priv))
    t = last_texts(S, 2)
    check("/start salomlashadi", any("Assalomu alaykum" in x for x in t))
    check("guruhga qo'shish taklifi bor", any("guruhga qo'shing" in x for x in t))
    await dp.feed_update(bot, H.upd_message("❓ Yordam", ali, priv))
    check("yordam matni", "Qo'llanma" in last_texts(S)[-1])

    print("\n━━━ 2. PRO REJIM (shaxsiy) ━━━")
    await dp.feed_update(bot, H.upd_message("🧠 Pro rejim", ali, priv))
    check("setup kartasi", "Pro rejim" in last_texts(S)[-1])
    check("boshlash tugmasi", "su:pro:go" in btns(S))
    # savollar sonini 3 ga qo'yamiz
    await db.set_pref(101, "count", 3)
    await dp.feed_update(bot, H.upd_call("su:pro:go", ali, priv))
    card = last_texts(S)[-1]
    check("pro savol kartasi", "1-savol" in card and "▱" in card, card[:80])
    sess = await db.active_session(101, "pro")
    sid = sess["id"]
    q0 = await db.question(sess["q_ids"][0])
    corr = sess["settings"]["perm"][0].index(q0["correct"])

    msg_id = S.calls[-1][2].message_id
    await dp.feed_update(bot, H.upd_call(f"pro:f:{sid}:0", ali, priv, msg_id))
    check("50:50 ishladi", "<s>" in S.messages[msg_id])
    await dp.feed_update(bot, H.upd_call(f"pro:l:{sid}:0", ali, priv, msg_id))
    check("«o'rgandim» belgilandi", await db.is_learned(101, q0["id"]))
    await dp.feed_update(bot, H.upd_call(f"pro:l:{sid}:0", ali, priv, msg_id))
    check("«o'rgandim» qaytarildi", not await db.is_learned(101, q0["id"]))
    await dp.feed_update(bot, H.upd_call(f"pro:map:{sid}:0", ali, priv, msg_id))
    check("savollar xaritasi", "xaritasi" in S.messages[msg_id])
    await dp.feed_update(bot, H.upd_call(f"pro:g:{sid}:1", ali, priv, msg_id))
    check("navigatsiya (2-savolga)", "2-savol" in S.messages[msg_id])

    # 3 ta savolga javob (1- to'g'ri, qolgani xato)
    await dp.feed_update(bot, H.upd_call(f"pro:a:{sid}:0:{corr}", ali, priv, msg_id))
    rows = await db.session_answers(sid, 101)
    check("javob bazaga yozildi", len(rows) == 1 and rows[0]["is_correct"] == 1)
    edits = [m.text for k, m, _ in S.calls if k == "EditMessageText"]
    check("javobdan keyin javob ochiladi",
          any("✅ To'g'ri!" in e for e in edits), edits[-1][:80] if edits else "")
    for i in (1, 2):
        c = sess["settings"]["perm"][i]
        qq = await db.question(sess["q_ids"][i])
        wrong = (c.index(qq["correct"]) + 1) % len(c)
        await dp.feed_update(bot, H.upd_call(f"pro:a:{sid}:{i}:{wrong}", ali, priv, msg_id))
    final = S.messages[msg_id]
    check("test yakunlandi", "yakunlandi" in final, final[:120])
    check("natijada 1/3", "1 / 3" in final, final[:200])
    check("xatolar tugmasi", any("pro:rev" in b for b in btns(S)))
    await dp.feed_update(bot, H.upd_call(f"pro:rev:{sid}:w:0", ali, priv, msg_id))
    check("xatolar tahlili", "Xatolar" in S.messages[msg_id] and "To'g'ri:" in S.messages[msg_id])
    await dp.feed_update(bot, H.upd_call(f"pro:rev:{sid}:all:0", ali, priv, msg_id))
    check("hamma javoblar ro'yxati", "Barcha javoblar" in S.messages[msg_id])
    s2 = await db.active_session(101, "pro")
    check("sessiya yopildi", s2 is None)

    print("\n━━━ 3. XATOLAR USTIDA ISHLASH ━━━")
    await dp.feed_update(bot, H.upd_call("su:pro:mistakes", ali, priv))
    check("xato savollardan test", "Xatolar ustida ish" in last_texts(S)[-1])
    ms = await db.active_session(101, "pro")
    check("faqat xato savollar olindi", ms and len(ms["q_ids"]) == 2, str(ms and ms['q_ids']))
    await dp.feed_update(bot, H.upd_call(f"pro:fin:{ms['id']}", ali, priv,
                                         S.calls[-1][2].message_id))
    await db.abort_active(101)

    print("\n━━━ 4. KLASSIK REJIM (shaxsiy, quiz-poll) ━━━")
    await db.set_pref(101, "timer", 10)
    await dp.feed_update(bot, H.upd_message("/quiz", ali, priv))
    check("klassik setup", "Klassik rejim" in last_texts(S)[-1])
    await dp.feed_update(bot, H.upd_call("su:classic:go", ali, priv))
    await asyncio.sleep(2.0)
    check("poll yuborildi", len(S.polls) >= 1, f"{len(S.polls)} ta")
    pid = list(S.polls)[-1]
    p = S.polls[pid]
    check("quiz tipida", p.type == "quiz" and p.correct_option_id is not None)
    check("poll savol limiti", len(p.question) <= 300)
    check("poll variant limiti", all(len(o) <= 100 for o in p.options))
    # 3 ta savolga to'g'ri javob beramiz
    for _ in range(3):
        await asyncio.sleep(0.4)
        pid = list(S.polls)[-1]
        await dp.feed_update(bot, H.upd_poll_answer(pid, ali, [S.polls[pid].correct_option_id]))
        await asyncio.sleep(1.6)
    await asyncio.sleep(1.5)
    res = [t for t in S.messages.values() if "Test yakunlandi" in t]
    check("klassik natija chiqdi", bool(res), str(list(S.messages.values())[-1])[:100])
    check("3/3 to'g'ri", bool(res) and "3 / 3" in res[-1], res[-1][:120] if res else "")

    print("\n━━━ 5. GURUH: lobbi + PRO JANG ━━━")
    await dp.feed_update(bot, H.upd_message("/pro", ali, grp))
    lob = last_texts(S)[-1]
    check("lobbi ochildi", "Guruh testi" in lob and "Pro jang" in lob, lob[:100])
    lob_mid = S.calls[-1][2].message_id
    for u in (ali, vali, sardor):
        await dp.feed_update(bot, H.upd_call("g:join", u, grp, lob_mid))
    check("3 qatnashchi qo'shildi", "Qatnashchilar (3)" in S.messages[lob_mid],
          S.messages[lob_mid][:200])
    await dp.feed_update(bot, H.upd_call("g:cnt", vali, grp, lob_mid))
    check("begona sozlay olmaydi", "Nechta savol" not in S.messages[lob_mid])
    await dp.feed_update(bot, H.upd_call("g:cnt", ali, grp, lob_mid))
    await dp.feed_update(bot, H.upd_call("g:set:cnt:3", ali, grp, lob_mid))
    await dp.feed_update(bot, H.upd_call("g:set:tmr:10", ali, grp, lob_mid))
    check("sozlamalar saqlandi", "Savollar: <b>3</b>" in S.messages[lob_mid],
          S.messages[lob_mid][:200])
    await dp.feed_update(bot, H.upd_call("g:go", ali, grp, lob_mid))
    await asyncio.sleep(2.6)
    gs = await db.fetch_one("SELECT id FROM sessions WHERE chat_id=-1001 AND mode='battle'"
                            " ORDER BY id DESC LIMIT 1")
    gsid = gs["id"]
    check("jang sessiyasi yaratildi", gsid is not None)
    for qi in range(3):
        for _ in range(40):
            if (gsid, qi) in group.BATTLE: break
            await asyncio.sleep(0.1)
        ctx = group.BATTLE.get((gsid, qi))
        if not ctx:
            check(f"{qi+1}-savol chiqdi", False, "BATTLE ctx yo'q"); break
        check(f"{qi+1}-savol chiqdi", True)
        # Ali to'g'ri, Vali to'g'ri, Sardor xato
        await dp.feed_update(bot, H.upd_call(f"gb:{gsid}:{qi}:{ctx['correct']}", ali, grp, ctx["msg_id"]))
        await dp.feed_update(bot, H.upd_call(f"gb:{gsid}:{qi}:{ctx['correct']}", ali, grp, ctx["msg_id"]))
        await asyncio.sleep(0.05)
        await dp.feed_update(bot, H.upd_call(f"gb:{gsid}:{qi}:{ctx['correct']}", vali, grp, ctx["msg_id"]))
        bad = (ctx["correct"] + 1) % len(ctx["shown"])
        await dp.feed_update(bot, H.upd_call(f"gb:{gsid}:{qi}:{bad}", sardor, grp, ctx["msg_id"]))
        await asyncio.sleep(3.4)
    rows = await db.session_answers(gsid)
    check("takroriy javob bloklandi", len([r for r in rows if r["user_id"] == 101]) == 3,
          f"{len([r for r in rows if r['user_id']==101])} ta")
    check("3 kishidan 9 ta javob", len(rows) == 9, f"{len(rows)} ta")
    fin = [t for t in S.messages.values() if "Pro jang yakunlandi" in t]
    check("jang yakuniy reytingi", bool(fin), str(list(S.messages.values())[-1])[:120])
    if fin:
        check("Ali g'olib (tezlik boncusi)", "G'olib: <b>Ali</b>" in fin[-1], fin[-1][-200:])
    await dp.feed_update(bot, H.upd_message("/reyting", ali, grp))
    check("/reyting ishladi", "reytingi" in last_texts(S)[-1])

    print("\n━━━ 6. GURUH: KLASSIK ━━━")
    await dp.feed_update(bot, H.upd_message("/quiz", ali, grp))
    gmid = S.calls[-1][2].message_id
    for u in (ali, vali):
        await dp.feed_update(bot, H.upd_call("g:join", u, grp, gmid))
    await dp.feed_update(bot, H.upd_call("g:set:cnt:2", ali, grp, gmid))
    await dp.feed_update(bot, H.upd_call("g:set:tmr:5", ali, grp, gmid))
    n_polls = len(S.polls)
    await dp.feed_update(bot, H.upd_call("g:go", ali, grp, gmid))
    await asyncio.sleep(3.0)
    check("guruhda poll chiqdi", len(S.polls) > n_polls)
    pid = list(S.polls)[-1]
    await dp.feed_update(bot, H.upd_poll_answer(pid, ali, [S.polls[pid].correct_option_id]))
    await dp.feed_update(bot, H.upd_poll_answer(pid, vali, [(S.polls[pid].correct_option_id + 1) % 4]))
    await asyncio.sleep(14.0)
    board = [t for t in S.messages.values() if "Reyting" in t and "🥇" in t]
    check("guruh reytingi chiqdi", bool(board), str(list(S.messages.values())[-1])[:120])
    await dp.feed_update(bot, H.upd_message("/stop", ali, grp))

    print("\n━━━ 7. IMPORT: JSON / DOCX / MATN ━━━")
    import docx
    tmp = "/tmp/claude-1000/-home-shaxobiddin-BOTS-quizbot/41e1ad43-3259-4c4d-94c4-3dfedfcf562b/scratchpad"
    d = docx.Document()
    for l in ["1. Test savol bir?", "+To'g'ri", "-Xato1", "-Xato2"]:
        d.add_paragraph(l)
    d.save(f"{tmp}/imp.docx")
    jsonb = json.dumps([{"question": "JSON savol?", "options": ["a", "b", "c"], "answer": 2}])

    async def fake_download(doc, *a, **k):
        return io.BytesIO(open(f"{tmp}/imp.docx", "rb").read() if doc.file_name.endswith(".docx")
                          else jsonb.encode())
    bot.download = fake_download

    await dp.feed_update(bot, H.upd_message("➕ Savol qo'shish", ali, priv))
    check("baza tanlash chiqdi", "qaysi bazaga" in last_texts(S)[-1])
    await dp.feed_update(bot, H.upd_call("lib:new", ali, priv))
    await dp.feed_update(bot, H.upd_message("Sinov bazasi", ali, priv))
    check("yangi baza yaratildi", "bazasi yaratildi" in last_texts(S)[-1])
    newcol = (await db.get_prefs(101))["collection_id"]

    doc = types.Document(file_id="f1", file_unique_id="u1", file_name="imp.docx", file_size=1000)
    upd = H.upd_message("", ali, priv, document=doc)
    await dp.feed_update(bot, upd)
    prev = [t for t in S.messages.values() if "Tahlil natijasi" in t]
    check("docx tahlil qilindi", bool(prev) and "1</b> ta savol" in prev[-1],
          prev[-1][:150] if prev else "")
    await dp.feed_update(bot, H.upd_call("lib:save", ali, priv, S.calls[-1][1].message_id
                                         if hasattr(S.calls[-1][1], "message_id") else None))
    check("docx saqlandi", await db.count_questions(newcol) == 1,
          str(await db.count_questions(newcol)))

    doc2 = types.Document(file_id="f2", file_unique_id="u2", file_name="imp.json", file_size=100)
    await dp.feed_update(bot, H.upd_message("", ali, priv, document=doc2))
    mid2 = [m for k, m, _ in S.calls if k == "EditMessageText"][-1].message_id
    await dp.feed_update(bot, H.upd_call("lib:save", ali, priv, mid2))
    check("json saqlandi", await db.count_questions(newcol) == 2,
          str(await db.count_questions(newcol)))
    # takror
    await dp.feed_update(bot, H.upd_message("", ali, priv, document=doc2))
    mid3 = [m for k, m, _ in S.calls if k == "EditMessageText"][-1].message_id
    await dp.feed_update(bot, H.upd_call("lib:save", ali, priv, mid3))
    check("takror savol filtrlandi", await db.count_questions(newcol) == 2,
          str(await db.count_questions(newcol)))

    await dp.feed_update(bot, H.upd_call(f"lib:addto:{newcol}", ali, priv))
    await dp.feed_update(bot, H.upd_message("1. Matndan savol?\n+ha\n-yo'q\n-balki", ali, priv))
    mid4 = [m for k, m, _ in S.calls if k == "EditMessageText"][-1].message_id
    await dp.feed_update(bot, H.upd_call("lib:save", ali, priv, mid4))
    check("matndan qo'shildi", await db.count_questions(newcol) == 3,
          str(await db.count_questions(newcol)))

    print("\n━━━ 8. BAZALAR / EKSPORT / STATISTIKA ━━━")
    await dp.feed_update(bot, H.upd_message("📚 Bazalar", ali, priv))
    check("bazalar ro'yxati", "Bazalar" in last_texts(S)[-1])
    await dp.feed_update(bot, H.upd_call(f"lib:open:{newcol}", ali, priv, S.calls[-1][2].message_id))
    await dp.feed_update(bot, H.upd_call(f"lib:export:{newcol}", ali, priv))
    check("JSON eksport", any(k == "SendDocument" for k, _, _ in S.calls))
    await dp.feed_update(bot, H.upd_call(f"lib:del:{newcol}", ali, priv))
    await dp.feed_update(bot, H.upd_call(f"lib:del2:{newcol}", ali, priv))
    check("baza o'chirildi", await db.collection(newcol) is None)
    check("default baza saqlanib qoldi",
          (await db.count_questions(await db.default_collection_id())) == 197)
    await dp.feed_update(bot, H.upd_message("📊 Statistika", ali, priv))
    st = last_texts(S)[-1]
    check("statistika", "statistikangiz" in st and "Aniqlik" in st, st[:120])

    print("\n━━━ 9. CHEGARAVIY HOLATLAR ━━━")
    await dp.feed_update(bot, H.upd_call("pro:a:999999:0:0", ali, priv))
    check("yo'q sessiyada yiqilmaydi", True)
    await dp.feed_update(bot, H.upd_call(f"gb:{gsid}:0:0", ali, grp))
    check("tugagan savolda yiqilmaydi", True)
    await dp.feed_update(bot, H.upd_message("/stop", vali, priv))
    check("faol test yo'q javobi", "faol test yo'q" in last_texts(S)[-1].lower())
    bad_doc = types.Document(file_id="f3", file_unique_id="u3", file_name="x.doc", file_size=10)
    await dp.feed_update(bot, H.upd_message("", ali, priv, document=bad_doc))
    check(".doc rad etildi", any(".doc" in t and "qo'llab" in t for t in S.messages.values()))

    await db.execute("DELETE FROM answers WHERE user_id IN (101,102,103)")
    await db.execute("DELETE FROM sessions WHERE owner_id IN (101,102,103)")
    await db.execute("DELETE FROM learned WHERE user_id IN (101,102,103)")
    await db.close()

    print("\n" + "═" * 46)
    print(f"  ✅ O'TDI: {len(OK)}      ❌ YIQILDI: {len(FAIL)}")
    if FAIL:
        for f in FAIL: print("   -", f)
    print("═" * 46)
    return 1 if FAIL else 0


async def _wrapped():
    try:
        return await main()
    finally:
        import contextlib
        with contextlib.suppress(Exception):
            await db.close()
        for t in asyncio.all_tasks():
            if t is not asyncio.current_task():
                t.cancel()

sys.exit(asyncio.run(_wrapped()))
