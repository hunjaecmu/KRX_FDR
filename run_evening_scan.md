# run_evening_scan.py

저녁 배치 스캔 실행 엔트리 문서입니다.

## 1. 역할 요약

`run_evening_scan.py`는 아래 작업을 한 번에 실행합니다.

1. 시장 돌파 스캔
2. 스캔 결과 CSV 저장
3. 개요 이미지 생성
4. 포지션 트래킹 스냅샷 저장
5. 차트 생성
6. HTML 리포트 생성

## 2. 실행 함수

### 2.1 run_once()

주요 흐름:

- 시작 시각 기록 + 타임스탬프 생성
- `scan_all_breakouts()` 실행
- `print_scan_results()` 출력
- `save_scan_results_to_csv()` 저장
- `create_overview_image()` 저장
- `run_position_tracking()` 실행
- `show_breakout_charts()` 실행
- `create_scan_overview_html()` 저장
- 종료 시각/총 소요시간 출력

예외 발생 시:

- `[RUN][FAIL]` 로그 출력 후 예외 재전파

### 2.2 run_daily_scheduler()

- `SCAN_HOUR`, `SCAN_MINUTE` 기준 하루 1회 실행
- 다음 실행까지 남은 시간을 계산해 대기
- 오류 발생 시 60초 후 재대기
- `KeyboardInterrupt` 시 종료

보조 함수:

- `seconds_until_target(hour, minute)`

## 3. 설정 의존성

`config.py`:

- `SCAN_HOUR`
- `SCAN_MINUTE`

## 4. 출력 산출물

실행 시 보통 아래 산출물이 생성됩니다.

- `output/scan_result_*/all_breakouts.csv`
- `output/scan_result_*/summary.csv`
- `output/scan_result_*/(케이스별 csv)`
- 개요 이미지 파일
- 차트 이미지들
- HTML 리포트
- 포지션 트래킹 스냅샷/히스토리

## 5. 기본 실행

현재 `__main__`에서 기본값은 즉시 1회 실행입니다.

```python
if __name__ == "__main__":
    run_once()
    # run_daily_scheduler()
```

## 6. 사용 예시

```bash
python run_evening_scan.py
```

스케줄 모드로 사용하려면 파일 하단에서 `run_daily_scheduler()`를 활성화하세요.

## 7. 의존성 모듈

- market_scanner.py
- chart_viewer.py
- position_tracker.py
- config.py
