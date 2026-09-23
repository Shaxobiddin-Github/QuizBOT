"""Klassik/jang testlari tugab, trafik tinchiguncha kutadi (restart uchun xavfsiz payt)."""
import datetime
import sqlite3
import sys
import time

DB = "/home/shaxobiddin/BOTS/quizbot/data/quiz.db"
QUIET_SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 40
MAX_WAIT = int(sys.argv[2]) if len(sys.argv) > 2 else 1800
STALE_MIN = 25          # bundan eski "faol" sessiya tashlab ketilgan hisoblanadi


def age_seconds(iso: str | None) -> float:
    if not iso:
        return 1e9
    ts = datetime.datetime.fromisoformat(iso)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=datetime.timezone.utc)
    return (datetime.datetime.now(datetime.timezone.utc) - ts).total_seconds()


def probe():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    live = sum(
        1 for r in conn.execute(
            "SELECT started_at FROM sessions "
            "WHERE status='active' AND mode IN ('classic','battle')")
        if age_seconds(r["started_at"]) < STALE_MIN * 60)
    last = conn.execute("SELECT MAX(created_at) FROM answers").fetchone()[0]
    conn.close()
    return live, age_seconds(last)


start = time.time()
while time.time() - start < MAX_WAIT:
    live, quiet = probe()
    if live == 0 and quiet >= QUIET_SECONDS:
        print(f"TINCH: faol klassik/jang yo'q, oxirgi javob {quiet:.0f}s oldin "
              f"({time.time() - start:.0f}s kutildi)")
        sys.exit(0)
    time.sleep(5)

live, quiet = probe()
print(f"KUTISH TUGADI: hamon band (faol={live}, oxirgi javob {quiet:.0f}s oldin)")
sys.exit(1)
