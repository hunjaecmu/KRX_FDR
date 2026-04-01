# historical_chart_viewer.py

과거 특정 시점 기준의 주봉/월봉 차트를 인터랙티브로 탐색하는 도구 문서입니다.

## 1. 역할 요약

`historical_chart_viewer.py`는 사용자가 종목/기준일/봉타입을 선택하면, 고정 봉 수(기본 52봉) 차트를 탐색할 수 있게 제공합니다.

주요 기능:

- 종목 선택(코드 직접입력 또는 종목명 prefix 검색)
- 기준일 선택(연도 + 월/일)
- 주봉/월봉 전환
- 키보드 탐색/저장

## 2. 탐색 규칙

- 표시 길이: `LOOKBACK_BARS = 52`
- 기준 인덱스(anchor)를 중심으로 슬라이딩
- 이동 키:
  - `Left/Right`: 1봉 이동
  - `Up/Down`: 10봉 이동
  - `Home/End`: 처음/끝
  - `S`: 현재 화면 저장
  - `Q` 또는 `Esc`: 종료

## 3. 차트 구성

- 캔들 + 거래량
- 이동평균: `ma5`, `ma10`, `ma20`, `ma120`, `ma180`, `ma240`
- 우측 상단 정보 박스: 종가/5/10/20/120/180/240이평
- 월봉에서도 `ma120` 포함 전체 MA를 동일하게 표시
- 이동평균선 색상 고정 팔레트 적용
- 월봉 x축은 분기성 월(1/3/6/9월) 중심으로 라벨 표시
- 상단 보조 텍스트: 조작키 안내

## 4. 저장 경로

- `OUTPUT_DIR/historical_charts/`
- 파일명 패턴:
  - `{code}_{name}_{주봉|월봉}_{anchor_date}.png`

## 5. 입력 흐름

1. 종목 선택
2. 기준일 입력
3. 봉타입 선택(주봉/월봉)
4. 인터랙티브 탐색 실행

## 6. 주요 함수/클래스

- `_configure_plot_font()`
- `select_stock()`
- `_parse_target_date()`
- `_parse_timeframe()`
- `HistoricalChartExplorer`
  - `_draw_once()`
  - `_on_key()`
  - `run()`
- `main()`

## 7. 사용 예시

```bash
python historical_chart_viewer.py
```

## 8. 의존성

- pandas
- matplotlib
- mplfinance
- data_loader.py
- config.py
