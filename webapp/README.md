# webapp

`web_app.py`에서 화면과 분리한 모듈 모음입니다. `theme*.css`를 제외하면 모두 Streamlit에 의존하지 않습니다.

| 파일 | 역할 |
|---|---|
| `storage.py` | 관심·패턴·보유 CSV 읽기/쓰기 ([문서](storage.md)) |
| `data_status.py` | 시장별 종목 수, 최신 데이터 일자 등 데이터 현황 계산 |
| `workflow.py` | 시작화면의 데이터 저장 → 돌파 서칭 → 결과 조회 진행 상태 계산 |
| `tv_chart.py` | TradingView Lightweight Charts 대화형 차트 데이터와 HTML 생성 |
| `thumbnails.py` | 경량·서버 버전의 어두운 축소 썸네일 생성 |
| `lite_data.py` | 서버 버전용 데이터 묶음 생성, 업로드, 내려받기, 설치 |
| `auto_publish.py` | 전체 업데이트와 스캔 후 데이터 묶음 자동 업로드 |
| `theme.css` | 공통 화면 스타일 |
| `theme_lite.css` | 경량·서버 버전의 터미널 색상 |
| `vendor/` | Lightweight Charts v5.2.1 파일과 라이선스 |

## tv_chart.py

- `build_payload(df, target_date, title, visible_bars, price_lines, marker_date)`
  - 기준일까지의 봉만 넣습니다. 복기 중에 이후 시세가 보이지 않도록 하기 위함입니다.
  - 처음에는 `visible_bars`만큼 보여 주고, 과거 전체 기간은 이동해서 볼 수 있습니다.
- `render_html(payload, height, theme)`
  - `LIGHT_THEME`(메인), `DARK_THEME`(서버)를 지정합니다.
  - 라이선스 조건을 위해 TradingView 로고(`attributionLogo`)를 끄지 않습니다.
  - 표시 구간은 iframe 크기가 잡힌 뒤에 적용합니다. 먼저 지정하면 전체 기간으로 펼쳐집니다.

라이브러리를 올릴 때는 `vendor/`의 파일과 `THIRD_PARTY_NOTICES.md`의 버전을 함께 바꿉니다.

## workflow.py

- 데이터 저장: 가장 뒤처진 시장의 최신 일자가 가장 최근 평일 이후이면 완료 (공휴일은 구분하지 않음)
- 돌파 서칭: 스캔 시각이 데이터 수집 시각보다 뒤이면 완료
- 결과 조회: 스캔이 완료되면 "볼 수 있음"이라는 뜻으로 완료 표시
- `mismatched_market_message`: 시장별 최신 일자가 다르면 경고 문구 반환

## auto_publish.py

- `publish_after(step)`: `scripts/publish_lite_data.py`를 별도 프로세스로 실행합니다. 환경변수가 없으면 건너뛰고, 실패해도 앞선 작업은 성공으로 유지합니다.
- `is_full_update(markets)`: 전체 시장 업데이트인지 판단합니다. 시장별 업데이트에서는 올리지 않습니다.
