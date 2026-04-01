# KRX_FDR 프로젝트

KRX(KOSPI/KOSDAQ) 시세 데이터를 수집하고, 이동평균 기반 돌파 스캔과 포지션 트래킹, 차트/리포트 생성을 수행하는 Python 프로젝트입니다.

## 프로젝트 목적

- 국내 주식 종목의 일봉 데이터를 로컬에 축적
- 일봉을 기반으로 주봉/월봉 파생 데이터 및 이동평균 생성
- 주봉/월봉 10/240이평 상향 돌파 종목 자동 탐지
- 보유/관심 종목의 현재 상태(수익률, 이평 거리) 스냅샷 관리
- 차트/오버뷰/HTML로 결과를 한 번에 확인

## 1) 이 프로젝트가 저장하는 데이터

`config.py`의 `DATA_DIR`, `OUTPUT_DIR`를 기준으로 아래 데이터를 저장합니다.

### A. 원천/파생 시세 데이터 (`DATA_DIR`)

- `master/kospi_tickers.csv`
  - KOSPI/KOSDAQ 종목 마스터
- `raw/daily/*.csv`
  - 종목별 원시 일봉 OHLCV
  - 실행 메타(`asof_datetime`, `asof_date`, `asof_time`, `price_status`) 포함
- `derived/daily/*.csv`
  - 일봉 + 이동평균(`ma5`, `ma10`, `ma20`, `ma120`, `ma180`, `ma240`)
- `derived/weekly/*.csv`
  - 주봉 집계 + 이동평균 + `is_final`
- `derived/monthly/*.csv`
  - 월봉 집계 + 이동평균 + `is_final`
- `logs/raw_update_result_*.csv`
  - 원시 데이터 업데이트 실행 결과 로그
- `logs/derived_update_result_*.csv`
  - 파생 데이터 생성 실행 결과 로그

### B. 포지션 트래킹 입력/출력

- 입력:
  - `tracking/holdings.csv`
- 출력 (`OUTPUT_DIR/position_tracking`):
  - `position_snapshot_YYYYMMDD_HHMMSS.csv`
  - `position_history.csv`

### B-1. 웹 앱 입력/기록 파일

- `tracking/watch.csv`
  - 웹 앱 관심종목 저장/조회 파일
- `tracking/MA10_J_Break.csv` 등
  - 웹 앱 패턴 기록 저장 파일 (`config.RECORD_FILE_OPTIONS`)

### C. 스캔 결과/차트 (`OUTPUT_DIR`)

- `scan_result_YYYYMMDD_HHMMSS/`
  - `all_breakouts.csv`
  - `summary.csv`
  - 케이스별 CSV (`weekly_ma10_breakout.csv` 등)
  - `overview.png`
  - `charts/<scan_case>/*.png`
  - `scan_overview_*.html`

## 2) 이 프로젝트가 가진 기능

### A. 데이터 수집/정규화

- FinanceDataReader 기반 KRX 종목/일봉 수집
- 증분 업데이트 + 재시도 로직
- 거래량 0 봉 보정 규칙 적용
  - `volume == 0`이면 OHLC를 마지막 거래일 종가로 보정
- 이동평균 계산 시 거래량 0 봉 제외

관련 모듈:

- `data_store.py`
- `data_loader.py`

### B. 시장 스캔

- 케이스:
  - 주봉 10이평 돌파
  - 주봉 240이평 돌파
  - 월봉 10이평 돌파
  - 월봉 240이평 돌파
- 돌파 조건:
  - 이전 봉 `close <= MA`
  - 현재 봉 `close > MA`
- 거래량 0 봉은 돌파 판정에서 제외
- 멀티프로세싱 스캔 지원

관련 모듈:

- `market_scanner.py`

### C. 시각화/리포팅

- 케이스별 캔들 차트 생성
- 오버뷰 이미지 생성
- 확대/탐색 가능한 HTML 결과 페이지 생성
- 자동 슬라이드 재생 기능

관련 모듈:

- `chart_viewer.py`
- `replay_latest_scan.py`
- `historical_chart_viewer.py`

### D. 포지션 트래킹

- 보유 종목 CSV 컬럼 자동 인식
- 현재가, 손익, 손익률 계산
- 주/월봉 MA10/MA240 거리 지표 계산
- 스냅샷 + 히스토리 누적 저장

관련 모듈:

- `position_tracker.py`
- `run_position_tracking.py`

### E. 실행 엔트리/배치

- 저녁 배치 1회 실행 또는 스케줄 실행
  - `run_evening_scan.py`
- 데이터 업데이트 전용 실행
  - `scripts/update_data.py`
- 스캔 전용 실행
  - `scripts/scan_market.py`

## 3) 최종 생성물(사용자가 확인하는 결과)

실행 후 사용자가 주로 확인하는 최종 결과는 다음입니다.

### A. 스캔 결과물

- `all_breakouts.csv`: 전체 돌파 종목 통합본
- `summary.csv`: 케이스별 종목 수 요약
- 케이스별 상세 CSV

### B. 시각화 결과물

- `overview.png`: 케이스별 전체/필터 요약 이미지
- `charts/.../*.png`: 종목별 돌파 차트
- `scan_overview_*.html`: 차트 갤러리형 리포트

### C. 포지션 관리 결과물

- `position_snapshot_*.csv`: 실행 시점 스냅샷
- `position_history.csv`: 스냅샷 누적 히스토리

## 빠른 시작

1. `config.py` 경로 설정 확인
  - 기본값: `프로젝트/.app_data/{data,output}`
  - 배포 환경: `APP_DATA_DIR` 또는 `DATA_DIR`/`OUTPUT_DIR` 환경변수 사용 권장
2. 데이터 업데이트 실행

```bash
python scripts/update_data.py
```

3. 스캔 실행

```bash
python run_evening_scan.py
```

4. 포지션 트래킹만 실행(선택)

```bash
python run_position_tracking.py
```

5. 웹 UI 실행(선택)

```bash
pip install streamlit
streamlit run web_app.py
```

## 문서

모듈별 상세 문서:

- `data_store.md`
- `data_loader.md`
- `market_scanner.md`
- `chart_viewer.md`
- `position_tracker.md`
- `run_evening_scan.md`
- `run_position_tracking.md`
- `historical_chart_viewer.md`
- `replay_latest_scan.md`
- `scripts/*.md`

## 참고

- `__pycache__/` 및 `*.py[cod]`는 `.gitignore`로 제외되어 있습니다.
