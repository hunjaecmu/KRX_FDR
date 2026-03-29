# data_store.py

KRX(KOSPI + KOSDAQ) 일봉 데이터를 수집하고, 파생 데이터(일/주/월봉 + 이동평균)를 생성하는 모듈 문서입니다.

## 1. 역할 요약

`data_store.py`는 아래 작업을 담당합니다.

- 종목 마스터 갱신 (`update_master`)
- 원시 일봉(raw) 수집/증분 업데이트 (`update_one_raw_stock`)
- 파생 데이터 생성
  - 일봉 (`build_daily_derived`)
  - 주봉 (`build_weekly_derived`)
  - 월봉 (`build_monthly_derived`)
- 전체 배치 실행 (`run_all`)

데이터 소스는 `FinanceDataReader`입니다.

## 2. 디렉터리 구조

`config.py`의 `DATA_DIR` 기준으로 아래 경로를 사용합니다.

- `master/kospi_tickers.csv`
- `raw/daily/*.csv`
- `derived/daily/*.csv`
- `derived/weekly/*.csv`
- `derived/monthly/*.csv`
- `logs/raw_update_result_YYYYMMDD_HHMMSS.csv`
- `logs/derived_update_result_YYYYMMDD_HHMMSS.csv`

## 3. 주요 설정값

파일 상단 상수:

- `START_YEARS_AGO = 25`
- `MA_WINDOWS = [5, 10, 20, 120, 240]`
- `MAX_RETRY = 3`
- `SLEEP_SEC_BETWEEN_TICKERS = 0.12`
- `SLEEP_SEC_BETWEEN_MASTER_CALLS = 0.02`
- 장마감 기준:
  - `MARKET_CLOSE_HOUR = 15`
  - `MARKET_CLOSE_MINUTE = 30`

## 4. 데이터 처리 규칙 (핵심)

### 4.1 거래량 0 봉 OHLC 보정

`normalize_zero_volume_ohlc` 규칙:

- `volume == 0`인 봉의 `open/high/low/close`는
- 직전 `volume > 0` 봉의 `close` 값으로 통일

목적:

- 비정상 0봉/placeholder 구간으로 인해 차트 형태와 집계가 왜곡되는 문제 완화

### 4.2 이동평균 계산 대상

`add_ma_columns` 규칙:

- 이동평균 계산에서 `volume == 0` 봉은 제외
- 즉 MA 소스 시계열은 `close where volume > 0`

결과:

- 거래 없는 봉이 연속되면 MA가 늦게 채워지거나 `NaN`이 될 수 있음
- 이는 의도된 동작이며, 잘못된 돌파 신호를 줄이는 목적

### 4.3 주봉/월봉 집계

- 주봉: `week_end`(금요일 기준)로 groupby
- 월봉: `month_end`(월말 기준)로 groupby
- 집계 방식:
  - `open`: 기간 첫 값
  - `high`: 기간 최대
  - `low`: 기간 최소
  - `close`: 기간 마지막 값
  - `volume`: 기간 합계

### 4.4 is_final 규칙

- 일봉: 항상 `True`
- 주봉: 최신 주가 금요일로 마감되었을 때만 `True`
- 월봉: 최신 일자가 월말과 동일할 때만 `True`

## 5. 실행 흐름

`run_all(force_master_update=False, derive_all=True)`

1. 디렉터리 생성 (`ensure_dirs`)
2. 마스터 갱신 (`update_master`)
3. 전체 종목 raw 업데이트 (`update_one_raw_stock`)
4. 전체(또는 업데이트 종목만) derived 생성 (`generate_derived_for_one_stock`)
5. 로그 CSV 저장

## 6. 함수 개요

- 경로/유틸
  - `raw_file_path`, `derived_*_file_path`, `ensure_dirs`
- 마스터
  - `normalize_fdr_listing`, `_fetch_listing_with_retry`, `update_master`
- 원시 데이터
  - `clean_fdr_ohlcv`, `fetch_ohlcv_with_retry`, `load_raw_daily`, `save_raw_daily`, `update_one_raw_stock`
- 파생 데이터
  - `build_daily_derived`, `build_weekly_derived`, `build_monthly_derived`, `save_derived_file`, `generate_derived_for_one_stock`
- 배치
  - `run_all`

## 7. 사용 예시

### 7.1 Python에서 직접 실행

```python
from data_store import run_all

run_all(
    force_master_update=False,
    derive_all=True,
)
```

### 7.2 스크립트 실행

프로젝트에는 실행용 스크립트가 있습니다.

- `scripts/update_data.py`

```bash
python scripts/update_data.py
```

## 8. 운영 권장 사항

- 로직 변경(예: MA 규칙 변경) 직후에는 1회 전체 재생성 권장
- 평시에는 증분 업데이트 사용 가능
- 분할/병합 이슈 의심 종목은 개별 raw+derived 재생성 권장
- `logs/*_result_*.csv` 상태값(`ok/fail/skip`)을 주기적으로 점검

## 9. 의존성

- Python
- pandas
- FinanceDataReader

`config.py`의 `DATA_DIR`/`OUTPUT_DIR`가 먼저 올바르게 설정되어 있어야 합니다.
