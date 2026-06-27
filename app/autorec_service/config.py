from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent  # = /srv/app/autorec_service/

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "vezeeta_alexandria_autorec.sqlite"
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(DEFAULT_DB_PATH)))
if not DATABASE_PATH.is_absolute():
    DATABASE_PATH = PROJECT_ROOT / DATABASE_PATH

MODELS_DIR = PROJECT_ROOT / "models"
MODELS_DIR.mkdir(exist_ok=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

AUTOREC_WEIGHT = float(os.getenv("AUTOREC_WEIGHT", "0.35"))
COLD_START_WEIGHT = float(os.getenv("COLD_START_WEIGHT", "0.65"))
