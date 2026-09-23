"""Default bazani (artifactdagi savollar) bir marta yuklash."""
from __future__ import annotations

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
