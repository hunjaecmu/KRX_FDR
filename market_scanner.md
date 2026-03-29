# market_scanner.py

주봉/월봉 이동평균 돌파 종목을 스캔하고 결과를 출력/저장하는 모듈 문서입니다.

## 1. 역할 요약

`market_scanner.py`는 마스터 종목 전체를 순회하면서 지정된 스캔 케이스(주봉/월봉 MA 돌파)를 검사합니다.

주요 기능:

- 돌파 판정 (`detect_breakout_up`)
- 종목별 스캔 (`_scan_one_stock`)
- 전체 병렬 스캔 (`scan_all_breakouts_parallel`)
- 결과 콘솔 출력 (`print_scan_results`)
- 결과 CSV 저장 (`save_scan_results_to_csv`)

## 2. 스캔 케이스

`SCAN_CASES`:

- `weekly_ma10_breakout`
- `weekly_ma240_breakout`
- `monthly_ma10_breakout`
- `monthly_ma240_breakout`

각 케이스는:

- `timeframe` (`weekly`/`monthly`)
- `ma_col` (`ma10`/`ma240`)
- 표시 라벨

## 3. 돌파 판정 규칙

`detect_breakout_up(df, ma_col)` 규칙:

1. `date`, `close`, `ma_col` 존재 여부 확인
2. 날짜순 정렬
3. `volume == 0` 봉은 판정 대상에서 제외
4. 최신 봉을 현재 봉으로 강제
5. 최신 봉의 `close` 또는 `ma`가 `NaN`이면 스킵
6. 이전 봉은 최신 봉 이전 구간에서 `close/ma` 유효한 마지막 봉 사용
7. 조건:
   - 이전 봉: `close <= MA`
   - 현재 봉: `close > MA`

출력 필드:

- `date`, `close`, `ma_value`
- `prev_close`, `prev_ma_value`
- `breakout_strength` (`close/ma - 1`)
- `breakout_pct`
- `is_final`

## 4. 병렬 처리

- 기본 worker: `max(1, os.cpu_count() - 1)`
- `ProcessPoolExecutor` 사용
- 100건 단위 진행률 출력
- worker 예외는 경고 출력 후 계속 진행

## 5. 결과 저장 구조

`save_scan_results_to_csv` 출력:

- `output/scan_result_YYYYMMDD_HHMMSS/`
  - `all_breakouts.csv`
  - `summary.csv`
  - `weekly_ma10_breakout.csv`
  - `weekly_ma240_breakout.csv`
  - `monthly_ma10_breakout.csv`
  - `monthly_ma240_breakout.csv`

정렬 기준:

- 기본적으로 `breakout_strength` 오름차순(낮은 값 먼저)

## 6. 인터페이스

- `scan_all_breakouts(max_workers=None)`
  - 외부 호출용 래퍼
- `print_scan_results(results)`
- `save_scan_results_to_csv(results, output_root=None, timestamp=None)`

## 7. 사용 예시

```python
from market_scanner import scan_all_breakouts, print_scan_results, save_scan_results_to_csv

results = scan_all_breakouts()
print_scan_results(results)
folder = save_scan_results_to_csv(results)
print(folder)
```

## 8. 의존성

- pandas
- data_loader.py
- config.py (`OUTPUT_DIR`)
