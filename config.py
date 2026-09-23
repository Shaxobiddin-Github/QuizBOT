"""Bot sozlamalari."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError(".env faylida BOT_TOKEN ko'rsatilmagan")

DB_PATH = BASE_DIR / os.getenv("DB_PATH", "data/quiz.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

SEED_FILE = BASE_DIR / "data" / "default_questions.json"
SEED_TITLE = "Psixologiya va Pedagogika"

ADMINS = {int(x) for x in os.getenv("ADMINS", "").replace(" ", "").split(",") if x.isdigit()}

# Telegram cheklovlari
POLL_QUESTION_LIMIT = 300
POLL_OPTION_LIMIT = 100
POLL_EXPLANATION_LIMIT = 200

# Standart test sozlamalari
DEFAULT_COUNT = 20
DEFAULT_TIMER = 30
TIMER_CHOICES = [10, 15, 30, 45, 60, 90]
COUNT_CHOICES = [10, 20, 30, 50, 100]
