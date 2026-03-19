# config.py

import os

SCAN_HOUR = 19
SCAN_MINUTE = 0

CHART_LOOKBACK_DAILY = 160
CHART_LOOKBACK_WEEKLY = 80
CHART_LOOKBACK_MONTHLY = 80

OUTPUT_DIR = r"D:\KRX_FDR_Data\output"
DATA_DIR = r"D:\KRX_FDR_Data\data"

TRACKING_INPUT_DIR = os.path.join(DATA_DIR, "tracking")
HOLDINGS_CSV = os.path.join(TRACKING_INPUT_DIR, "holdings.csv")
WATCHLIST_CSV = os.path.join(TRACKING_INPUT_DIR, "watchlist.csv")
TRACKING_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "position_tracking")

# manual: 화면 중심
# batch: 파일 저장 중심
RUN_MODE = "batch"   # "manual" or "batch"

if RUN_MODE == "manual":
    SHOW_CHART = True
    SAVE_CHART = False
else:
    SHOW_CHART = False
    SAVE_CHART = True