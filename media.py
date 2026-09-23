"""Savol rasmlari: yuklash, variant rasmlarini birlashtirish, file_id keshi va
bitta xabarni matn <-> rasm ko'rinishlari orasida xavfsiz almashtirish.

Rasm manbasi (`ref`) uch xil bo'lishi mumkin:
  * ``iq/m3_01.png`` — `config.MEDIA_DIR` ichidagi fayl (nisbiy yo'l)
  * ``https://…``   — internetdagi rasm
  * boshqa har qanday satr — Telegram `file_id`
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import ipaddress
import json
import logging
import re
import socket
from urllib.parse import urlparse

import aiohttp
from aiogram import Bot, types
from aiogram.exceptions import TelegramBadRequest
from PIL import Image, ImageDraw

import config
import db
from iq_gen import font

log = logging.getLogger("media")

CAPTION_LIMIT = 1024
MAX_DOWNLOAD = 10 * 1024 * 1024
MAX_SIDE = 1600
LETTERS = "ABCDEFGHIJ"
Image.MAX_IMAGE_PIXELS = 40_000_000


def has_media(q: dict) -> bool:
    return bool(q.get("image") or q.get("option_images"))


def has_option_images(q: dict) -> bool:
    return bool(q.get("option_images"))


def _local(ref: str):
    if not ref or ref.startswith(("http://", "https://")):
        return None
    root = config.MEDIA_DIR.resolve()
    path = (root / ref).resolve()
    if root in path.parents and path.is_file():
        return path
    return None


def is_url(ref: str) -> bool:
    return ref.startswith(("http://", "https://"))


def is_local(ref: str) -> bool:
    return _local(ref) is not None


async def _public_host(host: str) -> bool:
    """Ichki tarmoq manzillariga (localhost, 10.x, 192.168.x …) so'rov yubormaymiz."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            return False
    return True


async def fetch_url(url: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("noto'g'ri havola")
    if not await _public_host(parsed.hostname):
        raise ValueError("bu manzilga ruxsat yo'q")
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as s, \
            s.get(url, allow_redirects=False) as r:
        r.raise_for_status()
        data = await r.content.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise ValueError("rasm juda katta (10 MB dan oshmasin)")
    return data


async def load_bytes(bot: Bot, ref: str) -> bytes:
    path = _local(ref)
    if path:
        return path.read_bytes()
    if is_url(ref):
        return await fetch_url(ref)
    buf = await bot.download(ref)            # Telegram file_id
    return buf.read()


def store_image(raw: bytes, owner: int | str) -> str:
    """Rasmni tekshirib, qayta kodlab `MEDIA_DIR/u<owner>/` ga saqlaydi -> nisbiy yo'l."""
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:
        raise ValueError("fayl rasm emas yoki buzilgan") from exc
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    out = io.BytesIO()
    if img.mode in ("RGBA", "LA", "P"):
        img.convert("RGBA").save(out, format="PNG", optimize=True)
        ext = "png"
    else:
        img.convert("RGB").save(out, format="JPEG", quality=90)
        ext = "jpg"
    data = out.getvalue()
    rel = f"u{owner}/{hashlib.sha1(data).hexdigest()[:20]}.{ext}"
    path = config.MEDIA_DIR / rel
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return rel


# --------------------------------------------------------------- birlashtirish
def _cols(n: int) -> int:
    return {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 3, 7: 4, 8: 4}.get(n, 5)


def compose(question: bytes | None, options: list[bytes]) -> bytes:
    """Savol rasmi (tepada) + harflangan variant rasmlari (pastda) -> PNG."""
    width, pad, gap = 820, 24, 16
    parts: list[Image.Image] = []
    if question:
        q = Image.open(io.BytesIO(question)).convert("RGB")
        q.thumbnail((width - 2 * pad, 620), Image.LANCZOS)
        parts.append(q)

    cols = _cols(len(options))
    tile = min(180, (width - 2 * pad - (cols - 1) * gap) // cols)
    label_h = 38
    rows = (len(options) + cols - 1) // cols
    grid_h = rows * (tile + label_h) + (rows - 1) * gap
    height = pad + sum(p.height + pad for p in parts) + (grid_h + pad if options else 0)
    if parts and options:
        height += 10

    img = Image.new("RGB", (width, height), (255, 255, 255))
    d = ImageDraw.Draw(img)
    y = pad
    for p in parts:
        img.paste(p, ((width - p.width) // 2, y))
        y += p.height + pad
    if parts and options:
        d.line([(pad, y - pad // 2), (width - pad, y - pad // 2)], fill=(200, 200, 200), width=2)
        y += 10
    f = font(26)
    grid_w = cols * tile + (cols - 1) * gap
    x0 = (width - grid_w) // 2
    for i, raw in enumerate(options):
        r, c = divmod(i, cols)
        x = x0 + c * (tile + gap)
        yy = y + r * (tile + label_h + gap)
        o = Image.open(io.BytesIO(raw)).convert("RGB")
        o.thumbnail((tile - 8, tile - 8), Image.LANCZOS)
        d.rectangle([x, yy, x + tile, yy + tile], outline=(90, 90, 90), width=2)
        img.paste(o, (x + (tile - o.width) // 2, yy + (tile - o.height) // 2))
        d.text((x + tile / 2, yy + tile + label_h / 2), LETTERS[i], fill=(20, 20, 20),
               font=f, anchor="mm")
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


# --------------------------------------------------------------------- kesh
def cache_key(q: dict) -> str:
    raw = json.dumps([q.get("image") or "", q.get("option_images") or []])
    return "q:" + hashlib.sha1(raw.encode()).hexdigest()


async def photo_for(bot: Bot, q: dict):
    """Savol uchun yuboriladigan rasm: (kalit, media) yoki None."""
    if not has_media(q):
        return None
    key = cache_key(q)
    cached = await db.media_get(key)
    if cached:
        return key, cached
    try:
        if not has_option_images(q):
            ref = q["image"]
            path = _local(ref)
            if path:
                return key, types.FSInputFile(path)
            return key, ref                  # URL yoki file_id — Telegram o'zi oladi
        qbytes = await load_bytes(bot, q["image"]) if q.get("image") else None
        obytes = [await load_bytes(bot, ref) for ref in q["option_images"]]
        data = await asyncio.to_thread(compose, qbytes, obytes)
        return key, types.BufferedInputFile(data, filename="savol.png")
    except Exception as exc:
        log.warning("savol %s rasmi tayyorlanmadi: %s", q.get("id"), exc)
        return None


async def remember(key: str, msg) -> None:
    photo = getattr(msg, "photo", None)
    if photo:
        with contextlib.suppress(Exception):
            await db.media_put(key, photo[-1].file_id)


# ------------------------------------------------------------ yuborish/tahrir
_TAG = re.compile(r"<[^>]+>")


def _fit(text: str) -> tuple[str, str | None]:
    """Izoh 1024 belgidan oshsa — teglarsiz qisqartiramiz."""
    if len(text) <= CAPTION_LIMIT:
        return text, "HTML"
    plain = _TAG.sub("", text).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return plain[:CAPTION_LIMIT - 1] + "…", None


async def send(bot: Bot, chat_id: int, text: str, markup=None, photo=None) -> types.Message:
    if photo:
        key, media = photo
        caption, mode = _fit(text)
        try:
            msg = await bot.send_photo(chat_id, media, caption=caption, parse_mode=mode,
                                       reply_markup=markup)
            await remember(key, msg)
            return msg
        except TelegramBadRequest as exc:
            log.warning("rasm yuborilmadi (%s), matn bilan davom etamiz", exc)
    return await bot.send_message(chat_id, text, reply_markup=markup)


async def show(bot: Bot, chat_id: int, current, text: str, markup=None,
               photo=None) -> types.Message:
    """`current` xabarni yangi ko'rinishga keltiradi. Rasm/matn turi almashsa —
    eski xabar o'chiriladi va yangisi yuboriladi."""
    if current is not None:
        cur_photo = bool(getattr(current, "photo", None))
        try:
            if photo and cur_photo:
                key, media = photo
                caption, mode = _fit(text)
                msg = await bot.edit_message_media(
                    chat_id=chat_id, message_id=current.message_id,
                    media=types.InputMediaPhoto(media=media, caption=caption, parse_mode=mode),
                    reply_markup=markup)
                await remember(key, msg)
                return msg if isinstance(msg, types.Message) else current
            if not photo and not cur_photo:
                msg = await bot.edit_message_text(text, chat_id=chat_id,
                                                  message_id=current.message_id,
                                                  reply_markup=markup)
                return msg if isinstance(msg, types.Message) else current
        except TelegramBadRequest as exc:
            if "not modified" in str(exc):
                return current
            log.debug("tahrirlab bo'lmadi, qayta yuboramiz: %s", exc)
        with contextlib.suppress(TelegramBadRequest):
            await bot.delete_message(chat_id, current.message_id)
    return await send(bot, chat_id, text, markup, photo)


async def edit_card(bot: Bot, chat_id: int, message_id: int, is_photo: bool, text: str,
                    markup=None) -> None:
    """Rasm almashmaydigan kartani (masalan, guruh jangi) yangilash."""
    with contextlib.suppress(TelegramBadRequest):
        if is_photo:
            caption, mode = _fit(text)
            await bot.edit_message_caption(chat_id=chat_id, message_id=message_id,
                                           caption=caption, parse_mode=mode,
                                           reply_markup=markup)
        else:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id,
                                        reply_markup=markup)
