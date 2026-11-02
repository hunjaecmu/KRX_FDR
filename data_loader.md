# data_loader.py

저장된 CSV 데이터를 공통 규격으로 로딩하는 모듈 문서입니다.

## 1. 역할 요약

`data_loader.py`는 로컬 데이터 저장소에서 파일을 찾고, 스캔/추적 모듈이 바로 사용할 수 있도록 DataFrame으로 반환합니다.

주요 기능:

- 마스터 종목 로드 (`load_master`)
- 종목코드-종목명 맵 생성 (`get_name_map`)
- 코드별 종목명 조회 (`get_ticker_name`)
- 일/주/월 CSV 로드 (`load_raw_daily`, `load_daily`, `load_weekly`, `load_monthly`)

## 2. 데이터 경로

`config.py`의 `DATA_DIR`를 기준으로 다음 경로를 사용합니다.

- `master/kospi_tickers.csv`
- `raw/daily/*.csv`
- `derived/daily/*.csv`
- `derived/weekly/*.csv`
- `derived/monthly/*.csv`

## 3. 로딩 규칙

### 3.1 파일 검색

`_find_file(folder, code)`:

- `code`를 6자리로 정규화
- 파일명 패턴 `{code}_*.csv`에 매칭되는 파일 중 수정 시각이 가장 최근인 파일 반환
- 없으면 `None`

### 3.2 CSV 정규화

`_load_csv_with_date(file_path)`:

- `date` 컬럼이 있으면 datetime 변환
- 숫자형 후보 컬럼(`open/high/low/close/volume/ma*`)을 `to_numeric` 변환
- `is_final` 문자열(`true/false`)은 bool로 매핑
- `date` 오름차순 정렬 후 반환

## 4. 주요 함수

- `load_master() -> pd.DataFrame`
  - 코드 6자리 보정 + 코드순 정렬
- `get_name_map() -> dict`
  - `{code: name}` 사전 반환
- `get_ticker_name(code) -> str | None`
  - 코드로 단일 종목명 반환
- `load_raw_daily(code) -> pd.DataFrame`
- `load_daily(code) -> pd.DataFrame`
- `load_weekly(code) -> pd.DataFrame`
- `load_monthly(code) -> pd.DataFrame`

## 5. 예외/주의사항

- 파일이 없으면 `FileNotFoundError` 발생 가능
- 종목명 변경으로 동일 코드 파일이 여러 개이면 가장 최근에 갱신된 파일을 사용 (옛 이름의 파일은 자동 삭제되지 않음)
- 스키마가 달라진 CSV는 숫자 변환 과정에서 `NaN`이 생길 수 있음

## 6. 사용 예시

```python
from data_loader import load_master, load_weekly

master = load_master()
print(len(master))

w = load_weekly("005930")
print(w.tail(3)[["date", "close", "ma10", "volume"]])
```

## 7. 의존성

- pandas
- config.py (`DATA_DIR`)
