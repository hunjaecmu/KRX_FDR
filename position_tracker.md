# position_tracker.py

보유 종목 CSV를 읽어 현재 수익률과 이평 거리 지표를 스냅샷으로 저장하는 모듈 문서입니다.

## 1. 역할 요약

`position_tracker.py`는 보유 종목 입력 파일을 표준화하여, 종목별 최신 지표를 계산하고 결과를 파일로 저장합니다.

주요 기능:

- 입력 CSV 컬럼 자동 인식/정규화
- 현재가, 손익, 손익률 계산
- 주봉/월봉 MA10/MA240 대비 거리 계산
- 스냅샷 파일 + 누적 히스토리 저장

## 2. 입력/출력

입력 (`config.py`):

- `HOLDINGS_CSV`

출력 (`TRACKING_OUTPUT_DIR`):

- `position_snapshot_YYYYMMDD_HHMMSS.csv`
- `position_history.csv`

## 3. 컬럼 정규화

지원 후보 컬럼:

- 코드: `code`, `종목코드`, `티커`, `ticker`
- 이름: `name`, `종목명`
- 매수가: `buy_price`, `매수가`, `매입가`
- 수량: `quantity`, `보유수량`, `수량`, `shares`

표준 컬럼:

- `source`, `code`, `name`, `buy_price`, `quantity`

`source`는 내부적으로:

- 보유 = `H`

## 4. 계산 규칙

### 4.1 가격/거리

- 최신 일봉 `close`를 현재가로 사용
- 거리 비율: `price / ma - 1`
- 주봉/월봉 각각 `ma10`, `ma240` 거리 계산

### 4.2 손익

- `profit = current_price - buy_price`
- `profit_rate = profit / buy_price`
- `profit_amount = profit * quantity`

출력 문자열:

- 퍼센트 값은 `xx.x%` 문자열로 저장

### 4.3 경고 출력

보유(`H`) 종목에서 주봉/월봉 MA 거리 비율이 음수이면 콘솔에 Warning 출력

## 5. 주요 함수

- `load_targets(holdings_csv)`
- `build_snapshot(targets, now=None)`
- `save_snapshot(snapshot_df, output_dir, now=None)`
- `run_position_tracking(...)`

## 6. 반환 규격

`run_position_tracking` 성공:

- `status = ok`
- `rows`
- `snapshot_file`
- `history_file`

입력 없음:

- `status = no_targets`
- 메시지 + `holdings_csv` 경로

## 7. 사용 예시

```python
from position_tracker import run_position_tracking

result = run_position_tracking()
print(result)
```

## 8. 의존성

- pandas
- data_loader.py (일/주/월 로더)
- config.py (입출력 경로)
