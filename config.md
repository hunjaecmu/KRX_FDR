# config.py

프로젝트 전역 설정값을 정의하는 모듈 문서입니다.

## 1. 역할 요약

`config.py`는 스캔/차트/포지션트래킹 실행에 필요한 경로와 기본 파라미터를 제공합니다.

## 2. 설정 항목

### 2.1 스캔 스케줄

- `SCAN_HOUR = 19`
- `SCAN_MINUTE = 0`

`run_evening_scan.py`의 일일 스케줄러에서 사용됩니다.

### 2.2 차트 표시 범위

- `CHART_LOOKBACK_DAILY = 160`
- `CHART_LOOKBACK_WEEKLY = 80`
- `CHART_LOOKBACK_MONTHLY = 80`

### 2.3 입출력 루트 경로

- `OUTPUT_DIR = D:\KRX_FDR_Data\output`
- `DATA_DIR = D:\KRX_FDR_Data\data`

### 2.4 포지션 트래킹 경로

- `TRACKING_INPUT_DIR = DATA_DIR/tracking`
- `HOLDINGS_CSV = TRACKING_INPUT_DIR/holdings.csv`
- `WATCHLIST_CSV = TRACKING_INPUT_DIR/watchlist.csv`
- `TRACKING_OUTPUT_DIR = OUTPUT_DIR/position_tracking`

### 2.5 실행 모드

- `RUN_MODE = "batch"` 또는 `"manual"`
- `RUN_MODE`에 따라 자동 설정:
  - `manual`: `SHOW_CHART=True`, `SAVE_CHART=False`
  - `batch`: `SHOW_CHART=False`, `SAVE_CHART=True`

## 3. 운영 팁

- 경로가 로컬 환경과 다르면 먼저 `OUTPUT_DIR`, `DATA_DIR`를 수정하세요.
- 서버/자동배치에서는 보통 `RUN_MODE="batch"`를 권장합니다.
- 차트를 화면으로 확인하려면 `RUN_MODE="manual"`로 전환하세요.

## 4. 영향 모듈

- data_store.py
- data_loader.py
- market_scanner.py
- chart_viewer.py
- position_tracker.py
- run_evening_scan.py
