# QuizBot — ikki rejimli Telegram test boti

@quizbot_uzbot_bot · aiogram 3 · SQLite

## Rejimlar

| | 🎯 Klassik | 🧠 Pro | 🧩 IQ test |
|---|---|---|---|
| Shaxsiy chat | Telegram quiz-poll, taymer, avtomatik keyingi savol | Bitta xabar ichida navigatsiya, 50:50, «o'rgandim», xatolar tahlili | Rasmli matritsalar (Raven), IRT asosidagi deviatsion IQ |
| Guruh | Hamma poll'ga javob beradi, oxirida reyting | **Pro jang** — hamma bir vaqtda javob beradi, tezlik uchun bonus ball | — |

## 🧩 IQ test

Standartlashtirilgan testlar (Raven SPM/APM, WAIS «Matrix Reasoning») tuzilishida:

* **30 ta savol, 30 daqiqa**, osondan qiyiniga (qiyinlik ⭐1–⭐5);
* **12 ta rasmli matritsa** (3×3, «?» o'rniga mos figurani topish), figuralar
  ketma-ketligi, «ortiqcha figura», sonlar/harflar ketma-ketligi, analogiya,
  mantiqiy masalalar;
* uch kognitiv soha bo'yicha tahlil: vizual-fazoviy, son-miqdor, og'zaki-mantiqiy.

**Hisoblash** (`iq_score.py`): har savol IRT 3PL modeli bilan baholanadi
(qiyinlik b, ajratish a, taxmin ehtimoli c = 1/variantlar), qobiliyat θ EAP
usulida topiladi va **deviatsion IQ = 100 + 15·θ** (M=100, SD=15) ga
aylantiriladi. Natijada 95% ishonch oralig'i, persentil va WAIS-IV tasnifi
beriladi. Bot natijani ochiq yozadi: bu skrining test, klinik diagnostika emas —
normalar reprezentativ tanlanmadan emas, model parametrlaridan olingan.

**Rasmli savollar** (`iq_gen.py`) qat'iy seed bilan generatsiya qilinadi:
50 ta matritsa (har darajada 10 ta), 12 ta ketma-ketlik, 9 ta ortiqcha figura.
Qoidalar: son progressiyasi, «uchtadan taqsimlash» (lotin kvadrati), qatorda
doimiylik, burilish, qo'shish; noto'g'ri variantlar APM uslubida — to'g'ri
javobdan bitta-ikkita belgisi bilan farq qiladi. Rasmlar `data/media/iq/` ga
bir marta yoziladi, Telegram `file_id` keshlanadi.

## 🖼 Rasmli savollar

Savolda ham, javob variantlarida ham rasm bo'lishi mumkin — barcha rejimlarda
(Pro, Klassik, guruh jangi, IQ). Variantlari rasm bo'lsa, bot savol rasmi va
harflangan variantlarni bitta rasmga birlashtiradi, tugmalar A, B, C… bo'ladi.

Qo'shish usullari:

* **Rasm + izoh**: «➕ Savol qo'shish» → bazani tanlang → rasm yuboring, izohiga
  savol va variantlarni yozing (`+` to'g'ri javob).
* **ZIP**: ichida bitta `.json` va rasmlar:
  ```json
  [{"question": "Qaysi figura mos?", "image": "img/1.png",
    "option_images": ["img/a.png", "img/b.png", "img/c.png"], "answer": "B"}]
  ```
* **JSON** ichida `https://` havola — bot rasmni import paytida yuklab oladi
  (ichki tarmoq manzillari rad etiladi).

## 🔐 Ruxsatlar

Har bir foydalanuvchi **o'z bazasini** yaratadi. Qo'shilgan savollar sukut bo'yicha
**faqat egasiga** ko'rinadi. Egasi «📚 Bazalar» → baza → «🔐 Kim ko'ra oladi?» orqali:

| Rejim | Kim ko'radi |
|---|---|
| 🔒 Faqat men | faqat egasi |
| 👥 Tanlangan guruhlar | belgilangan Telegram guruhlari a'zolari |
| 🌍 Hamma | botning barcha foydalanuvchilari |

Guruh ro'yxatda chiqishi uchun bot o'sha guruhga qo'shilgan va foydalanuvchi u yerda
bot bilan bir marta ishlagan bo'lishi kerak. A'zolik `getChatMember` orqali
tekshiriladi (30 daqiqa keshlanadi), guruhdan chiqqan odam avtomatik kirish
huquqini yo'qotadi.

Guruhda o'yin faqat **o'sha guruhga ochilgan** bazalardan boshlanadi.

## 📣 Ommaviy xabar

`/faoliyat` — admin uchun boshqaruv paneli: foydalanuvchilar (jami, yangi, faol,
bloklaganlar), testlar (sessiyalar, rejimlar kesimi, javoblar, umumiy aniqlik),
guruhlar (a'zolar, o'yinlar, ochilgan bazalar, oxirgi faollik), bazalar va
eng faol foydalanuvchilar. To'rt bo'lim tugmalar bilan almashtiriladi.
👥 Guruhlar bo'limida har bir guruhga **o'tish tugmasi** bor: ochiq guruhlarda
`@username` yoki taklif havolasi, yopiq guruhlarda `t.me/c/…` (u faqat guruh
a'zolari uchun ochiladi).

`/tozalash` — admin uchun avtomatik tozalash: bot guruhlarga yuborgan xabarlar
(test savollari, natijalar, e'lonlar) belgilangan muddatdan keyin o'chiriladi.
Muddat 1/3/6/12/24/48 soat, yoqib-o'chirish va «hozir tozalash» tugmasi bor.
📌 Qadalgan xabarlar hech qachon o'chirilmaydi.

`/fayllar` — guruhda: fayllar arxivi (nomi, sanasi, kim yuborgani), xabarga
havola va faylni qayta olish tugmasi bilan. Bot **admin** bo'lsa, guruh a'zolari
tashlagan fayllarni ham yig'ib boradi — ular avtomatik tozalashdan himoyalanadi.

**Botni guruhda admin qilish** quyidagilarni yoqadi:
- 📌 ommaviy xabarni qadash (*Pin messages* huquqi),
- 📎 a'zolar tashlagan fayllarni arxivlash (admin barcha xabarlarni ko'radi),
- 🧹 eski xabarlarni ishonchli o'chirish (*Delete messages* huquqi).

> **Cheklov:** Telegram Bot API botga chat tarixini qidirishga ruxsat bermaydi.
> Shuning uchun `/fayllar` va tozalash faqat bot o'zi yozib borgan xabarlar
> ustida ishlaydi — ya'ni bu funksiya qo'shilgandan keyingilari. Bundan tashqari
> Telegram 48 soatdan eski xabarni o'chirishga ruxsat bermasligi mumkin.

`/xabar` — admin uchun. Yuborishdan oldin 📌 **«Qadab qo'yish»** ni yoqsangiz,
xabar har bir guruhda avtomatik qadaladi (bot admin bo'lishi va «xabar qadash»
huquqiga ega bo'lishi kerak). Qabul qiluvchi: barcha foydalanuvchilar, barcha guruhlar
yoki bitta tanlangan guruh. Matn, rasm, video, fayl — hammasi `copyMessage` orqali
o'z ko'rinishida yetkaziladi. Jonli progress, botni bloklaganlar avtomatik belgilanadi.

Admin `.env` dagi `ADMINS` ro'yxati bilan belgilanadi; bo'sh bo'lsa birinchi
ro'yxatdan o'tgan foydalanuvchi admin bo'ladi. O'z ID'ingizni bilish: `/id`.

## Boshqaruv

```bash
./bot-ctl.sh status     # holati
./bot-ctl.sh start      # ishga tushirish
./bot-ctl.sh stop       # to'xtatish
./bot-ctl.sh restart    # qayta ishga tushirish
./bot-ctl.sh log        # jonli log
./bot-ctl.sh test       # 140+ integratsion test
```

Bot **cron** nazorati ostida: har daqiqada tekshiriladi, o'chib qolsa
60 soniya ichida o'zi ko'tariladi, server qayta yuklansa `@reboot` bilan
avtomatik ishga tushadi. `flock` ikkinchi nusxa ishga tushishiga yo'l qo'ymaydi.

```
crontab -l
@reboot /LOYIHA/PAPKASI/keepalive.sh
* * * * * /LOYIHA/PAPKASI/keepalive.sh
```

Nazoratni butunlay o'chirish: `crontab -e` → ikkala qatorni o'chiring.

## Buyruqlar

**Shaxsiy:** `/start` `/quiz` `/pro` `/iq` `/bazalar` `/qoshish` `/stats` `/stop` `/help` `/id`
**Admin:** `/faoliyat` (statistika), `/xabar` (ommaviy xabar), `/tozalash` (avtomatik tozalash), `/bekor`
**Guruh:** `/quiz` `/pro` `/reyting` `/fayllar` `/stop`

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
iq_gen.py         rasmli IQ savollari generatori (Raven matritsalari)
iq_score.py       IQ hisobi: IRT 3PL, EAP, deviatsion IQ
media.py          rasmlar: birlashtirish, file_id keshi, xabarni almashtirish
bg.py             fon vazifalari
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
  library.py      bazalar, import/eksport, ruxsatlar
  iq.py           3-rejim (IQ test)
  admin.py        ommaviy xabar (broadcast)
access.py         kirish huquqi, guruh a'zoligi keshi
recorder.py       yuborilgan xabarlarni yozish va avtomatik tozalash
data/quiz.db      baza
data/default_questions.json   197 ta test savoli
data/iq_questions.json        52 ta matnli IQ savoli
data/media/       rasmlar (generatsiya qilingan va yuklangan; git'ga kirmaydi)
tests/            integratsion testlar (soxta Telegram API)
```

## Xavfsizlik

Bot tokeni `.env` faylida. Token uchinchi shaxsga ko'rinib qolgan bo'lsa,
@BotFather → `/revoke` → yangi tokenni `.env` ga yozing → `./bot-ctl.sh restart`.
