"""Default bazani (artifactdagi savollar) bir marta yuklash."""
from __future__ import annotations

import asyncio
import json
import logging

import config
import db
import importers

log = logging.getLogger("seed")


async def ensure_default() -> None:
    existing = await db.fetch_one(
        "SELECT id FROM collections WHERE is_default=1 LIMIT 1")
    if existing:
        n = await db.count_questions(existing["id"])
        if n:
            log.info("Default baza mavjud: %s ta savol", n)
            return
        col_id = existing["id"]
    else:
        col_id = None

    if not config.SEED_FILE.exists():
        log.warning("Seed fayl topilmadi: %s", config.SEED_FILE)
        return

    payload = json.loads(config.SEED_FILE.read_text(encoding="utf-8"))
    result = importers.parse_json(json.dumps(payload, ensure_ascii=False))
    if col_id is None:
        col_id = await db.create_collection(
            payload.get("title", config.SEED_TITLE),
            owner_id=None,
            description=payload.get("description", ""),
            is_default=1,
            visibility="public",
        )
    added, dup = await db.add_questions(col_id, result.questions)
    log.info("Default baza yuklandi: +%s ta savol (takror: %s)", added, dup)


async def ensure_iq() -> None:
    """IQ savollar bazasi: matnli savollar (JSON) + rasmli Raven matritsalari."""
    iq_file = config.BASE_DIR / "data" / "iq_questions.json"
    if not iq_file.exists():
        return
    row = await db.fetch_one(
        "SELECT id FROM collections WHERE COALESCE(kind,'quiz')='iq' ORDER BY id LIMIT 1")
    payload = json.loads(iq_file.read_text(encoding="utf-8"))
    if row:
        col_id = row["id"]
    else:
        col_id = await db.create_collection(
            payload.get("title", "IQ test"), owner_id=None,
            description=payload.get("description", ""),
            visibility="public", kind="iq")
    result = importers.parse_json(json.dumps(payload, ensure_ascii=False))
    added, dup = await db.add_questions(col_id, result.questions)
    if added:
        log.info("IQ bazasi yuklandi: +%s ta savol (takror: %s)", added, dup)

    import iq_gen
    bank = await asyncio.to_thread(iq_gen.build_bank, config.MEDIA_DIR)
    added, dup = await db.add_questions(col_id, bank)
    if added:
        log.info("Rasmli IQ savollari: +%s ta (takror: %s)", added, dup)
