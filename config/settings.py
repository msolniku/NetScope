import json
import os
from pathlib import Path

from dotenv import load_dotenv


# --------------------------------------------------
# Project root & env loading
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


# --------------------------------------------------
# Paths
# --------------------------------------------------

DATA_DIR       = PROJECT_ROOT / "data"
SCREENSHOT_DIR = PROJECT_ROOT / "screenshots"

SNAPSHOT_FILE  = DATA_DIR / "snapshots.jsonl"        # append-only, one JSON object per line
LEGACY_SNAPSHOT_FILE = DATA_DIR / "snapshots.json"  # old format, auto-migrated
DELTA_FILE     = DATA_DIR / "deltas.json"
ISP_FILE       = DATA_DIR / "isp_usage.json"
DATASET_FILE   = DATA_DIR / "dataset.json"
ISP_STATE_FILE = DATA_DIR / "isp_state.json"


# --------------------------------------------------
# Router
# --------------------------------------------------

ROUTER_URL      = os.getenv("ROUTER_URL", "http://192.168.1.1/wlclients.htm")
ROUTER_USERNAME = os.getenv("ROUTER_USERNAME", "")
ROUTER_PASSWORD = os.getenv("ROUTER_PASSWORD", "")


# --------------------------------------------------
# ISP
# --------------------------------------------------

ISP_LOGIN_URL = os.getenv("ISP_LOGIN_URL", "https://ecare.asiatech.ir/home")
ISP_CDR_URL   = os.getenv("ISP_CDR_URL", "https://ecare.asiatech.ir/form/cdr_report")


# --------------------------------------------------
# Browser
# --------------------------------------------------

CHROME_PATH = os.getenv(
    "CHROME_PATH",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
)
VIEWPORT       = {"width": 1400, "height": 900}
PAGE_SETTLE_MS = int(os.getenv("PAGE_SETTLE_MS", "3000"))


# --------------------------------------------------
# Timing
# --------------------------------------------------

DEFAULT_INTERVAL_SEC = int(os.getenv("SCREENSHOT_INTERVAL", "600"))


# --------------------------------------------------
# Analysis
# --------------------------------------------------

MAX_INTERVAL_SECONDS = int(os.getenv("MAX_INTERVAL_SECONDS", str(15 * 60)))
MAX_GAP_FACTOR       = float(os.getenv("MAX_GAP_FACTOR", "3.0"))


# --------------------------------------------------
# OCR
# --------------------------------------------------

TESSERACT_CMD = os.getenv(
    "TESSERACT_CMD",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
)

# OCR corrections — privacy-sensitive, kept in .env only.
try:
    MAC_CORRECTIONS: dict[str, str] = json.loads(
        os.getenv("MAC_CORRECTIONS_JSON", "{}")
    )
except json.JSONDecodeError:
    MAC_CORRECTIONS = {}

try:
    _tx_raw = json.loads(os.getenv("TX_RATE_CORRECTIONS_JSON", "{}"))
    TX_RATE_CORRECTIONS: dict[float, float] = {
        float(k): float(v) for k, v in _tx_raw.items()
    }
except (json.JSONDecodeError, ValueError):
    TX_RATE_CORRECTIONS = {}