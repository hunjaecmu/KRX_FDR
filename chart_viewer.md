# chart_viewer.py

스캔 결과를 캔들 차트/오버뷰 이미지/HTML 리포트로 시각화하는 모듈 문서입니다.

## 1. 역할 요약

`chart_viewer.py`는 주봉/월봉 데이터를 이용해 다음을 생성합니다.

- 개별 돌파 차트 (`show_candle_chart`, `show_breakout_charts`)
- 오버뷰 이미지 (`create_overview_image`)
- 자동 슬라이드 (`auto_slide_breakout_charts`)
- HTML 갤러리 리포트 (`create_scan_overview_html`)

## 2. 주요 설정

`config.py` 의존:

- `OUTPUT_DIR`
- `CHART_LOOKBACK_WEEKLY`
- `CHART_LOOKBACK_MONTHLY`
- `SHOW_CHART`
- `SAVE_CHART`

렌더링 동작:

- `SHOW_CHART=False`일 때 `Agg` 백엔드 사용(배치 환경 안정성)

## 3. 차트 데이터/케이스

`CASE_META`로 케이스별 메타를 관리합니다.

- `weekly_ma10_breakout`
- `weekly_ma240_breakout`
- `monthly_ma10_breakout`
- `monthly_ma240_breakout`

기본 이동평균 표시선:

- `ma5`, `ma10`, `ma20`, `ma120`, `ma240`

## 4. 표시 규칙

- OHLCV 필수 컬럼 검증 후 mplfinance 포맷으로 변환
- 돌파 대상 MA는 더 두껍게 하이라이트
- 마지막 봉 정보 박스(종가/10/120/240이평) 표시
- 제목에 종목, 타임프레임, 돌파 강도, 데이터 기준일/시각, 장중/종가 상태 표시

## 5. 오버뷰/필터

`_filter_results_by_breakout_pct`:

- 기본 필터 범위: `0.5% ~ 5.0%`

`create_overview_image`:

- 케이스별 전체 종목수/필터 종목수 표 생성
- `overview.png` 저장

## 6. HTML 리포트

`create_scan_overview_html`:

- 케이스별 차트 PNG를 갤러리 형태로 정리
- 확대(lightbox), 이전/다음 탐색, 요약 테이블 제공
- 정렬 기준: `strength` 또는 `code`

## 7. 주요 함수

- `show_candle_chart(...)`
- `show_breakout_charts(results, save_root=None)`
- `create_overview_image(...)`
- `auto_slide_breakout_charts(...)`
- `create_scan_overview_html(...)`

## 8. 사용 예시

```python
from chart_viewer import create_overview_image, show_breakout_charts

overview_path = create_overview_image(results, save_root=save_folder)
show_breakout_charts(results, save_root=save_folder)
```

## 9. 의존성

- pandas
- matplotlib
- mplfinance
- data_loader.py
- config.py
