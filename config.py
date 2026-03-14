# config.py

SCAN_HOUR = 19
SCAN_MINUTE = 0

CHART_LOOKBACK_DAILY = 160
CHART_LOOKBACK_WEEKLY = 120
CHART_LOOKBACK_MONTHLY = 140

OUTPUT_DIR = "output"

# manual: 화면 중심
# batch: 파일 저장 중심
RUN_MODE = "batch"   # "manual" or "batch"

if RUN_MODE == "manual":
    SHOW_CHART = True
    SAVE_CHART = False
else:
    SHOW_CHART = False
    SAVE_CHART = True