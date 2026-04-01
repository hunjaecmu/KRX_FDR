import os
from pathlib import Path

SCAN_HOUR = 19
SCAN_MINUTE = 0

CHART_LOOKBACK_DAILY = 160
CHART_LOOKBACK_WEEKLY = 80
CHART_LOOKBACK_MONTHLY = 80

BASE_DIR = Path(__file__).resolve().parent
APP_DATA_DIR = Path(os.getenv("APP_DATA_DIR", str(BASE_DIR / ".app_data")))

DATA_DIR = os.getenv("DATA_DIR", str(APP_DATA_DIR / "data"))
OUTPUT_DIR = os.getenv("OUTPUT_DIR", str(APP_DATA_DIR / "output"))

TRACKING_INPUT_DIR = os.path.join(DATA_DIR, "tracking")
HOLDINGS_CSV = os.path.join(TRACKING_INPUT_DIR, "holdings.csv")
INTEREST_WATCH_CSV = os.path.join(TRACKING_INPUT_DIR, "watch.csv")
TRACKING_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "position_tracking")

RECORD_FILE_OPTIONS = [
    ("주봉 10이평 돌파 매매", "MA10_J_Break.csv"),
    ("주봉 240이평 돌파 매매", "MA240_J_Break.csv"),
    ("월봉 10이평 돌파 매매", "MA10_W_Break.csv"),
    ("월봉 120이평 돌파 매매", "MA120_W_Break.csv"),
    ("월봉 180이평 돌파 매매", "MA180_W_Break.csv"),
    ("월봉 240이평 돌파 매매", "MA240_W_Break.csv"),
]

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TRACKING_INPUT_DIR, exist_ok=True)
os.makedirs(TRACKING_OUTPUT_DIR, exist_ok=True)

# manual: 화면 중심
# batch: 파일 저장 중심
RUN_MODE = "batch"   # "manual" or "batch"

if RUN_MODE == "manual":
    SHOW_CHART = True
    SAVE_CHART = False
else:
    SHOW_CHART = False
    SAVE_CHART = True