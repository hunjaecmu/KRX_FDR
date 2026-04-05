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

### 2.3 배포 친화 경로 설정

- `BASE_DIR = Path(__file__).resolve().parent`
- `APP_DATA_DIR = os.getenv("APP_DATA_DIR", BASE_DIR/.app_data)`
- `DATA_DIR = os.getenv("DATA_DIR", APP_DATA_DIR/data)`
- `OUTPUT_DIR = os.getenv("OUTPUT_DIR", APP_DATA_DIR/output)`

우선순위:

1. `DATA_DIR`, `OUTPUT_DIR` 환경변수
2. `APP_DATA_DIR` 환경변수
3. 기본값(`프로젝트/.app_data`)

### 2.4 포지션 트래킹 경로

- `TRACKING_INPUT_DIR = DATA_DIR/tracking`
- `HOLDINGS_CSV = TRACKING_INPUT_DIR/holdings.csv`
- `INTEREST_WATCH_CSV = TRACKING_INPUT_DIR/watch.csv`
- `TRACKING_OUTPUT_DIR = OUTPUT_DIR/position_tracking`

참고:

- `web_app.py`의 관심종목 저장/조회는 현재 `watch_YYYYMM.csv`(월별 파일) 중심으로 동작합니다.
- `INTEREST_WATCH_CSV`는 legacy 경로 호환을 위해 유지됩니다.

### 2.5 웹 입력/기록 파일 옵션

- `RECORD_FILE_OPTIONS`
  - 주/월봉 분류별 고정 저장 파일명 목록
  - `web_app.py`에서 패턴 데이터 저장 파일 선택에 사용

### 2.6 실행 모드

- `RUN_MODE = "batch"` 또는 `"manual"`
- `RUN_MODE`에 따라 자동 설정:
  - `manual`: `SHOW_CHART=True`, `SAVE_CHART=False`
  - `batch`: `SHOW_CHART=False`, `SAVE_CHART=True`

## 3. 운영 팁

- Streamlit Cloud 등 호스팅 환경에서는 코드 수정 대신 환경변수 설정을 권장합니다.
  - `APP_DATA_DIR` 또는 `DATA_DIR`/`OUTPUT_DIR`
- `config.py`는 시작 시 데이터/출력/tracking 폴더를 자동 생성합니다.
- 서버/자동배치에서는 보통 `RUN_MODE="batch"`를 권장합니다.
- 차트를 화면으로 확인하려면 `RUN_MODE="manual"`로 전환하세요.

## 4. 영향 모듈

- data_store.py
- data_loader.py
- market_scanner.py
- chart_viewer.py
- position_tracker.py
- run_evening_scan.py
