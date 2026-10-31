"""Paths and defaults. Override with environment variables."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # repo root
BACKEND = ROOT / "backend"
VAGDHENU = Path(os.environ.get("SS_VAGDHENU", ROOT / "EdgeSanskrit-TTS" / "vagdhenu"))
BIGVGAN_DIR = Path(os.environ.get("SS_BIGVGAN", ROOT / "EdgeSanskrit-TTS" / "BigVGAN"))
MODELS = VAGDHENU / "models"
SRC = VAGDHENU / "src"
BANK_JSON = SRC / "reference_bank" / "bank.json"
STORAGE = Path(os.environ.get("SS_STORAGE", BACKEND / "storage"))
DB_PATH = Path(os.environ.get("SS_DB", STORAGE / "app.db"))
SEED_FILE = Path(os.environ.get("SS_SEED", BACKEND / "seed" / "verses.json"))

DEFAULT_STEPS = 16
DEFAULT_SEED = 50

# --- external services (override in .env or the environment; see .env.example) ---
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://sloka:sloka@localhost:5433/sloka")
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://sloka:sloka@localhost:5433/sloka_test")
STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "s3")          # "s3" or "memory" (tests)
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://localhost:9000")  # empty string = real AWS S3
S3_BUCKET = os.environ.get("S3_BUCKET", "sloka")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "sloka")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "sloka-secret-1")
S3_REGION = os.environ.get("S3_REGION", "us-east-1")
S3_PATH_STYLE = os.environ.get("S3_PATH_STYLE", "true").lower() == "true"

# --- SQLite mirror of the Postgres data (see backup.py) ---
BACKUP_SQLITE_PATH = Path(os.environ.get("BACKUP_SQLITE_PATH", ROOT / "backups" / "sloka_mirror.sqlite"))
BACKUP_INTERVAL_S = float(os.environ.get("BACKUP_INTERVAL_S", "60"))      # 0 disables the background mirror
BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "5"))                     # rotated generations kept
