# QuizBot — ikki rejimli Telegram test boti

@quizbot_uzbot_bot · aiogram 3 · SQLite

## Rejimlar

| | 🎯 Klassik | 🧠 Pro |
|---|---|---|
| Shaxsiy chat | Telegram quiz-poll, taymer, avtomatik keyingi savol | Bitta xabar ichida navigatsiya, 50:50, «o'rgandim», xatolar tahlili |
| Guruh | Hamma poll'ga javob beradi, oxirida reyting | **Pro jang** — hamma bir vaqtda javob beradi, tezlik uchun bonus ball |

Ikkala rejim **bitta umumiy bazadan** ishlaydi.

## Boshqaruv

```bash
./bot-ctl.sh status     # holati
./bot-ctl.sh start      # ishga tushirish
./bot-ctl.sh stop       # to'xtatish
./bot-ctl.sh restart    # qayta ishga tushirish
./bot-ctl.sh log        # jonli log
./bot-ctl.sh test       # 59 ta integratsion test
```

Bot **cron** nazorati ostida: har daqiqada tekshiriladi, o'chib qolsa
60 soniya ichida o'zi ko'tariladi, server qayta yuklansa `@reboot` bilan
avtomatik ishga tushadi. `flock` ikkinchi nusxa ishga tushishiga yo'l qo'ymaydi.

```
crontab -l
@reboot /home/shaxobiddin/BOTS/quizbot/keepalive.sh
* * * * * /home/shaxobiddin/BOTS/quizbot/keepalive.sh
```

Nazoratni butunlay o'chirish: `crontab -e` → ikkala qatorni o'chiring.

## Buyruqlar

**Shaxsiy:** `/start` `/quiz` `/pro` `/bazalar` `/qoshish` `/stats` `/stop` `/help`
**Guruh:** `/quiz` `/pro` `/reyting` `/stop`

## Savol qo'shish formatlari

JSON (4 xil shakl qo'llab-quvvatlanadi):
```json
[{"question": "Savol?", "options": ["a","b","c"], "answer": 0}]
[{"q": "Savol?", "c": "to'g'ri", "a": ["xato","xato"]}]
```

Word / matn:
```
1. Savol matni?        1. Savol?          Savol ==== +to'g'ri ==== xato
+To'g'ri javob         A) bir
-Xato                  B) ikki
-Xato                  Javob: B
```
Belgisiz format ham o'qiladi — u holda birinchi variant to'g'ri deb olinadi
va bot bu haqda ogohlantiradi. Import qilishdan oldin namuna ko'rsatiladi.

## Fayllar

```
bot.py            ishga tushirish nuqtasi
config.py         sozlamalar (.env dan o'qiydi)
db.py             SQLite (umumiy baza)
importers.py      JSON / DOCX / TXT parserlari
ui.py             klaviatura va matn yordamchilari
seed.py           default bazani yuklash
handlers/
  group.py        guruh lobbisi + Pro jang
  menu.py         bosh menyu, statistika
  setup.py        test sozlamalari kartasi
  classic.py      1-rejim (quiz-poll)
  pro.py          2-rejim (inline interfeys)
  library.py      bazalar, import/eksport
data/quiz.db      baza          data/default_questions.json  197 ta savol
tests/            integratsion testlar (soxta Telegram API)
```

## Xavfsizlik

Bot tokeni `.env` faylida. Token uchinchi shaxsga ko'rinib qolgan bo'lsa,
@BotFather → `/revoke` → yangi tokenni `.env` ga yozing → `./bot-ctl.sh restart`.
