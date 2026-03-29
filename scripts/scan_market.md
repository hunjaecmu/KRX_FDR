# scripts/scan_market.py

시장 돌파 스캔을 단독 실행하는 간단 엔트리 스크립트 문서입니다.

## 1. 역할 요약

`scan_market.py`는 다음 순서로 동작합니다.

1. `scan_all_breakouts()` 실행
2. 콘솔 출력 (`print_scan_results`)
3. CSV 저장 (`save_scan_results_to_csv`)
4. 차트 표시/저장 (`show_breakout_charts`)

## 2. 사용 시점

- 스캔 기능만 빠르게 실행하고 싶을 때
- 스케줄러/부가 기능 없이 결과 확인이 필요할 때

## 3. 실행 예시

```bash
python scripts/scan_market.py
```

## 4. 의존성

- market_scanner.py
- chart_viewer.py
