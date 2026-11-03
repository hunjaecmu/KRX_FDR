# web_app.py

Streamlit 기반 통합 대시보드 모듈 문서입니다.

## 1. 역할 요약

[web_app.py](web_app.py)는 데이터 저장, 스캔 실행, 스캔 결과 조회, 관심/기록/보유 종목 조회를 하나의 화면에서 수행하는 웹 UI 엔트리입니다.

주요 기능:

- 데이터 업데이트 실행 및 실시간 로그 표시
- 시장 스캔 실행 및 진행률 표시
- 최신 스캔 결과 필터/정렬/갤러리 조회
- 관심종목 저장/조회
- 패턴 기록 저장/조회
- 보유 종목 수익률 및 이격도 조회
- TradingView Lightweight Charts 대화형 차트

## 2. 메뉴 구성

같은 코드를 환경변수 `KRX_APP_EDITION`으로 나눠 세 가지 버전으로 실행합니다.

| 메뉴 (`?menu=` 번호) | 메인 | 경량 (`lite`) | 서버 (`cloud`) |
|---|---|---|---|
| 시작화면 (0) | O | O | O |
| 1. 데이터 저장 (1) | O | O | - |
| 2. 이평 돌파 종목 서칭 (2) | O | O | - |
| 3. 서칭 데이터 조회 (3) | O | O | "돌파 종목 조회" |
| 4. 관심종목 서칭 (4) | O | "4. 종목 차트 조회" | "종목 차트 조회" |
| 5. 관심종목 조회 (5) | O | - | - |
| 6. 패턴 데이터 입력 (6) | O | - | - |
| 7. 패턴 데이터 조회 (7) | O | - | - |
| 8. 보유 종목 조회 (8) | O | - | - |
| 주요 종목 (9) | - | - | O |
| 사용 가이드 (10) | O | O | O |

- 실행: 메인은 `streamlit run web_app.py`, 경량은 `python web_app_lite.py`, 서버는 `lite/streamlit_app.py`
- 메뉴 번호는 모든 버전에서 같고, 해당 버전에 없는 번호는 시작화면으로 이동합니다.
- 경량과 서버 버전에는 관심저장 기능이 없고, 서버 버전에는 업데이트와 스캔도 없습니다.

메뉴 상태는 query parameter menu와 session state를 함께 사용하여 유지합니다.

## 2-1. 화면 테마

- 색상, 글꼴, 모서리: `.streamlit/config.toml` (프로젝트 폴더에서 `streamlit run`을 실행해야 적용)
- 테마 설정으로 지정할 수 없는 사이드바 메뉴, 카드 등의 스타일: `webapp/theme.css`
- 시작화면의 작업 진행 표시 상태 계산: `webapp/workflow.py` (공휴일은 구분하지 않음)

## 3. 의존 모듈

주요 의존성:

- streamlit
- pandas
- streamlit-image-select (선택 기능, 미설치 시 폴백 UI)

내부 모듈:

- [config.py](config.py)
- [data_loader.py](data_loader.py)
- [historical_chart_viewer.py](historical_chart_viewer.py)
- [webapp/](webapp/README.md) (저장소, 데이터 현황, 진행 상태, 대화형 차트, 데이터 묶음)

사용하는 config 상수:

- DATA_DIR
- OUTPUT_DIR
- TRACKING_INPUT_DIR
- HOLDINGS_CSV
- MA_BREAK_CSV

## 4. 입력/출력 파일

### 4.1 조회 입력

- 마스터/시세 데이터: DATA_DIR 하위 csv
- 보유 종목: HOLDINGS_CSV
- 관심 종목: TRACKING_INPUT_DIR 하위 `watch_YYYYMM.csv` (월별 파일)
	- 예: `watch_202604.csv`
	- `watch.csv` legacy 파일도 선택 조회 지원
- 패턴 기록: `tracking/ma_break.csv` (`패턴` 컬럼으로 구분)

### 4.2 실행 산출물

데이터 저장 메뉴:

- [data_store.py](data_store.py) 실행 결과 로그 출력

스캔 실행 메뉴:

- [scripts/scan_market.py](scripts/scan_market.py) 실행 결과 로그 출력
- OUTPUT_DIR 하위 최신 scan_result 폴더 갱신

관심/기록 저장 메뉴:

- tracking/watch_YYYYMM.csv
- tracking/ma_break.csv 패턴 기록 파일

## 5. 핵심 동작

### 5.1 데이터 저장

- [data_store.py](data_store.py)를 subprocess로 실행
- stdout/stderr 통합 로그를 실시간 렌더링
- 로그 패턴에서 RAW/DERIVED 진행률 파싱
- 전체 업데이트를 주 버튼으로 두고, 시장별 업데이트는 접힌 영역에 배치
- 전체 업데이트가 끝나면 지수를 갱신하고 서버용 데이터 묶음을 자동 업로드
- 시장별 최신 일자가 다르면 메뉴 1, 2번에 경고 표시

### 5.2 스캔 실행

- [scripts/scan_market.py](scripts/scan_market.py)를 백그라운드 subprocess로 실행하고 stdout/stderr를 임시 로그 파일에 기록
- 프로세스 핸들은 `st.cache_resource`로 서버 전체에서 공유하므로, 메뉴 이동·새로고침 후에도 실행 중인 스캔에 다시 연결됨
- 스캔이 끝나면 서버용 데이터 묶음을 자동 업로드
- `st.fragment(run_every=1)`가 1초마다 로그 파일의 끝 일부(256KB)만 읽어 SCAN/CHART 진행률과 마지막 24줄만 표시 (메뉴 이동이 막히지 않음)
- 종료 감지 시 로그/종료 코드/최신 스캔 폴더를 session_state에 반영하고 전체 화면을 한 번 재실행
- 데이터 저장(1번) 로그 루프는 출력이 없을 때 `time.sleep(0.05)`를 두고, 라이브 로그 렌더링을 0.5초 단위로 제한

### 5.3 스캔 결과 조회

- latest scan_result의 all_breakouts.csv 및 charts 폴더를 결합
- 케이스별 정렬(돌파율 내림차순/돌파율 오름차순/종목코드 오름차순)과 필터(돌파율, 볼륨%) 적용. 돌파율 0.5% 미만은 항상 제외
- 차트 갤러리 및 썸네일 선택 제공
- 확대(선택) 종목을 관심종목 파일로 바로 저장 가능 (메인 버전)
- 큰 차트는 메인과 서버 버전에서 대화형 차트, 경량 버전에서 저장된 PNG
- 썸네일은 저장된 PNG 사용, 경량과 서버 버전은 어두운 축소 이미지로 변환
- 차트 위에 봉 날짜와 확정/진행 중 여부 표시
- 케이스 버튼에 필터 적용 건수 표시, 요약표는 접힌 영역
- `all_breakouts.csv` 읽기 실패는 오류로 표시하고, 값이 없으면 `N/A` 표시
- 썸네일 부품은 이미지를 처음 한 번만 그리므로 목록이 바뀌면 위젯 키를 바꿔 새로 만듭니다.

streamlit-image-select가 없으면:

- selectbox 기반 종목 선택 폴백 제공
- 앱 전체는 중단되지 않고 계속 동작

### 5.4 관심종목/패턴 입력

- 코드 직접입력 또는 종목명 prefix 검색으로 종목 선택
- 주봉/월봉 및 기준일 기반 차트 조회
- 기준 봉 스냅샷(row)을 csv에 append 저장

### 5.5 관심종목/패턴 조회

- 저장된 csv를 페이지 단위로 조회
- 차트에 기준봉 가격선과 "기준" 표시
- 행 선택 + 액션 버튼(차트/삭제) 방식
- 관심종목 조회(5번):
	- 월별 파일 선택 조회
	- 차트에서 메모 필드 표시/수정/저장
	- 긴 메모 스크롤 지원
- 패턴조회(7번):
	- 테이블 앞 5열 폭 축소, 메모 열 폭 확장
- 이전/다음 봉 이동 지원

### 5.6 보유 종목 조회

- HOLDINGS_CSV를 읽어 현재가/수익률/이격도 계산
- 보유 종목 추가(종목코드/종목명/매수가/수량/메모)
- 테이블 선택 후 주봉/월봉 차트 조회
- 보유 행 삭제 지원
	- 삭제 시 관심종목으로 전송 가능(주봉/월봉, 분류, 메모)
- 보유 CSV 메모 컬럼 자동 보강
- 차트 표시 시 메모 조회/수정/저장 지원
- 차트에 매수가 선 표시

### 5.7 대화형 차트

- `_build_stock_chart`가 메뉴 3~8번과 주요 종목의 큰 차트를 준비합니다.
- 메인과 서버 버전은 [webapp/tv_chart.py](webapp/tv_chart.py), 경량 버전은 Matplotlib 이미지를 사용합니다.
- 기준일 이후 시세는 넣지 않으며, 처음에는 52봉을 보여 주고 과거 구간은 이동해서 봅니다.
- 차트 위에서 휠을 굴리면 페이지가 아니라 차트가 확대됩니다.

### 5.8 시작화면

- 메인: 작업 진행 표시, 데이터 현황, 다른 기능 목록, 케이스별 건수
- 경량·서버: 조회 가능한 데이터 설명, 데이터 현황, 케이스별 건수, 오픈소스 및 면책 고지

### 5.9 주요 종목 (서버 버전)

- 메뉴를 고르면 KOSPI, KOSDAQ의 최신 거래일 종가와 등락률, KOSPI 주봉을 먼저 표시합니다.
- 지수는 데이터 묶음에 있을 때만 표시합니다.
- 항목을 고르면 주봉부터 보여 주고 주봉과 월봉을 전환할 수 있습니다.

### 5.10 사용 가이드

- [webapp/user_guide.html](webapp/user_guide.html)을 화면에 표시합니다.
- 버전에 맞는 내용만 보여 줍니다. 서버 버전에는 저장, 운영, 배포 안내가 나오지 않습니다.
- 서버 버전은 Revolut 디자인 값을 참고한 어두운 테마, 메인과 경량 버전은 밝은 테마입니다.
- 메뉴나 동작을 바꾸면 이 파일도 함께 고칩니다.

## 6. 상태 관리

주요 session state:

- selected_menu
- data_store_logs, data_store_running
- scan_market_logs, scan_market_running
- scan_progress_value, scan_progress_text
- 각 메뉴별 선택 행, 페이지 인덱스, 차트 기준일 상태

실행 중에는 버튼 비활성화와 확인 플로우(중복 실행 방지)를 사용합니다.

## 7. 오류 처리

- csv 읽기/파싱 실패 시 사용자 메시지 출력
- subprocess 종료코드 비정상 시 실패 상태 표시
- 데이터 부재, 컬럼 누락, 날짜 파싱 실패 등은 메뉴별 안내 문구로 처리

## 8. 배포 관련 참고

- 경로는 [config.py](config.py)의 환경변수 기반 설정을 따릅니다.
- Streamlit Cloud 배포는 서버 버전을 사용합니다. 구조와 절차는 [lite/deploy.md](lite/deploy.md)를 참고하세요.

## 9. 실행 방법

로컬 실행:

```bash
streamlit run web_app.py
```

배포 전 확인:

1. `lite/requirements.txt`의 패키지 버전과 `THIRD_PARTY_NOTICES.md` 일치 여부
2. 데이터 묶음 업로드 여부와 Secrets 설정 여부
