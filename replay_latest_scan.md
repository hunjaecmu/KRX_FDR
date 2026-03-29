# replay_latest_scan.py

최신 스캔 결과 폴더를 다시 불러와 오버뷰/차트를 재생하는 스크립트 문서입니다.

## 1. 역할 요약

`replay_latest_scan.py`는 저장된 최신 `scan_result_*` 폴더를 찾아 결과 CSV를 읽고, 시각화 루틴을 다시 실행합니다.

주요 기능:

- 최신 스캔 폴더 자동 탐색
- 케이스별 CSV 로드
- 로드 요약 출력
- 오버뷰 이미지 생성/표시
- 돌파 차트 자동 슬라이드

## 2. 동작 흐름

1. `_find_latest_scan_result_folder(OUTPUT_DIR)`
2. `load_results_from_scan_folder(scan_folder)`
3. `print_loaded_summary(...)`
4. `create_overview_image(...)`
5. `auto_slide_breakout_charts(...)`

## 3. 대상 케이스

- `weekly_ma10_breakout`
- `weekly_ma240_breakout`
- `monthly_ma10_breakout`
- `monthly_ma240_breakout`

## 4. CSV 로딩 보정

`_load_case_csv`에서:

- 숫자 컬럼 `to_numeric` 변환
- `is_final` 문자열 bool 매핑

## 5. 실행 예시

```bash
python replay_latest_scan.py
```

## 6. 의존성

- pandas
- config.py (`OUTPUT_DIR`)
- chart_viewer.py
