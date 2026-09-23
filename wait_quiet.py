"""Klassik/jang testlari tugab, trafik tinchiguncha kutadi (restart uchun xavfsiz payt)."""
import sqlite3, sys, time, datetime

DB = "/home/shaxobiddin/BOTS/quizbot/data/quiz.db"
QUIET_SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 40
MAX_WAIT = int(sys.argv[2]) if len(sys.argv) > 2 else 1800
STALE_MIN = 25          # bundan eski "faol" sessiya tashlab ketilgan hisoblanadi

start = time.time()
while time.time() - start < MAX_WAIT:
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    now = datetime.datetime.now(datetime.timezone.utc)
    live = 0
    for r in c.execute("SELECT started_at FROM sessions "
                       "WHERE status='active' AND mode IN ('classic','battle')"):
        age = (now - datetime.datetime.fromisoformat(r["started_at"])).total_seconds() / 60
        if age < STALE_MIN:
            live += 1
    recent = c.execute(
        "SELECT COUNT(*) FROM answers WHERE created_at > datetime('now', ?)",
        (f"-{QUIET_SECONDS} seconds",)).fetchone()[0]
    c.close()
    if live == 0 and recent == 0:
        print(f"TINCH: faol klassik/jang yo'q, {QUIET_SECONDS}s javob yo'q "
              f"({time.time()-start:.0f}s kutildi)")
        sys.exit(0)
    time.sleep(5)
print("KUTISH TUGADI: hamon band")
sys.exit(1)
