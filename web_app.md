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

## 2. 메뉴 구성

메뉴는 아래 순서로 구성됩니다.

1. 시작화면
2. 데이터 저장
3. 이평 돌파 종목 서칭
4. 서칭 데이터 조회
5. 관심종목 서칭
6. 관심종목 조회
7. 패턴 데이터 입력
8. 패턴 데이터 조회
9. 보유 종목 조회

메뉴 상태는 query parameter menu와 session state를 함께 사용하여 유지합니다.

## 3. 의존 모듈

주요 의존성:

- streamlit
- pandas
- streamlit-image-select (선택 기능, 미설치 시 폴백 UI)

내부 모듈:

- [config.py](config.py)
- [data_loader.py](data_loader.py)
- [historical_chart_viewer.py](historical_chart_viewer.py)

사용하는 config 상수:

- DATA_DIR
- OUTPUT_DIR
- TRACKING_INPUT_DIR
- HOLDINGS_CSV
- RECORD_FILE_OPTIONS

## 4. 입력/출력 파일

### 4.1 조회 입력

- 마스터/시세 데이터: DATA_DIR 하위 csv
- 보유 종목: HOLDINGS_CSV
- 관심 종목: TRACKING_INPUT_DIR 하위 `watch_YYYYMM.csv` (월별 파일)
	- 예: `watch_202604.csv`
	- `watch.csv` legacy 파일도 선택 조회 지원
- 패턴 기록: TRACKING_INPUT_DIR 하위 RECORD_FILE_OPTIONS의 파일명

### 4.2 실행 산출물

데이터 저장 메뉴:

- [data_store.py](data_store.py) 실행 결과 로그 출력

스캔 실행 메뉴:

- [scripts/scan_market.py](scripts/scan_market.py) 실행 결과 로그 출력
- OUTPUT_DIR 하위 최신 scan_result 폴더 갱신

관심/기록 저장 메뉴:

- tracking/watch_YYYYMM.csv
- tracking/MA10_J_Break.csv 등 패턴 기록 파일

## 5. 핵심 동작

### 5.1 데이터 저장

- [data_store.py](data_store.py)를 subprocess로 실행
- stdout/stderr 통합 로그를 실시간 렌더링
- 로그 패턴에서 RAW/DERIVED 진행률 파싱

### 5.2 스캔 실행

- [scripts/scan_market.py](scripts/scan_market.py)를 subprocess로 실행
- 로그 패턴에서 SCAN/CHART 진행률 파싱
- 완료 후 최신 스캔 폴더 상태 갱신

### 5.3 스캔 결과 조회

- latest scan_result의 all_breakouts.csv 및 charts 폴더를 결합
- 케이스별 정렬(강도순/코드순)과 필터(돌파율, 볼륨%) 적용
- 차트 갤러리 및 썸네일 선택 제공
- 확대(선택) 종목을 관심종목 파일로 바로 저장 가능

streamlit-image-select가 없으면:

- selectbox 기반 종목 선택 폴백 제공
- 앱 전체는 중단되지 않고 계속 동작

### 5.4 관심종목/패턴 입력

- 코드 직접입력 또는 종목명 prefix 검색으로 종목 선택
- 주봉/월봉 및 기준일 기반 차트 조회
- 기준 봉 스냅샷(row)을 csv에 append 저장

### 5.5 관심종목/패턴 조회

- 저장된 csv를 페이지 단위로 조회
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
- Streamlit Cloud에서는 APP_DATA_DIR 또는 DATA_DIR, OUTPUT_DIR 설정을 권장합니다.
- 로컬 파일 저장은 호스팅 환경에서 영구 보존이 제한될 수 있으므로 필요 시 외부 스토리지 연동을 고려하세요.

## 9. 실행 방법

로컬 실행:

```bash
streamlit run web_app.py
```

배포 전 확인:

1. requirements.txt에 streamlit, streamlit-image-select 포함 여부
2. config 경로 환경변수 설정 여부
3. tracking 폴더 입력 파일 존재 여부(holdings.csv 등)
