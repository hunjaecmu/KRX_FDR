# KRX FDR Lite 배포 정리

조회 전용 경량 버전을 Streamlit Community Cloud에 비공개로 배포하기까지 적용한 내용을 정리한 문서입니다.

작성일: 2026-11-03

## 1. 전체 구조

코드와 데이터를 서로 다른 저장소에 둡니다.

| 저장소 | 공개 범위 | 내용 |
|---|---|---|
| `hunjaecmu/KRX_FDR` | 공개 | 코드. Streamlit Cloud가 `main` 브랜치를 실행 |
| `hunjaecmu/KRX_FDR_data` | 비공개 | 데이터 묶음(`krx_lite_data.zip`). Release `lite-data`에 보관 |

```text
[이 PC] 전체 업데이트 → scan → publish_lite_data.py
                                      │ 업로드 (쓰기 토큰)
                                      ▼
                     KRX_FDR_data Release: krx_lite_data.zip
                                      │ 내려받기 (읽기 토큰, 1시간마다 확인)
                                      ▼
[Streamlit Cloud] lite/streamlit_app.py → web_app.py (조회 전용)
```

시세 수집과 스캔은 이 PC에서만 실행합니다. 서버는 받은 데이터를 보여 주기만 합니다.

## 2. 세 가지 실행 버전

코드는 `web_app.py` 하나를 함께 쓰고, 환경변수 `KRX_APP_EDITION`으로 구분합니다.

| 버전 | 실행 방법 | 메뉴 | 데이터 | 테마 |
|---|---|---|---|---|
| 전체 | `streamlit run web_app.py` | 시작화면, 1~8번 | 로컬 CSV | 밝은 테마 |
| 경량 (`lite`) | `python web_app_lite.py` (포트 8502) | 시작화면, 1~4번 | 로컬 CSV | 터미널 테마 |
| 서버 (`cloud`) | `lite/streamlit_app.py` | 시작화면, 돌파 종목 조회, 종목 차트 조회, 주요 종목 | 내려받은 묶음 | 터미널 테마 |

- 경량과 서버 버전에는 관심저장 기능이 없습니다.
- 서버 버전에는 데이터 업데이트와 스캔 메뉴도 없습니다.
- 주소의 메뉴 번호(`?menu=3`)는 모든 버전에서 같습니다. 해당 버전에 없는 번호는 시작화면으로 이동합니다.
- 서버 버전을 CSV가 아닌 Parquet로 읽도록 `lite/streamlit_app.py`가 `KRX_DATA_SOURCE=parquet`를 설정합니다.

## 3. 파일별 변경 내용

### 배포 전용으로 추가한 파일

| 파일 | 역할 |
|---|---|
| `lite/streamlit_app.py` | Cloud 진입점. 서버 버전으로 설정한 뒤 `web_app.py`를 실행 |
| `lite/.streamlit/config.toml` | 서버용 터미널 테마. 진입점 옆 설정이 저장소 루트 설정보다 우선 |
| `lite/requirements.txt` | 서버용 패키지 목록 (버전 고정) |
| `packages.txt` | 차트 한글 글꼴(`fonts-nanum`). 반드시 저장소 루트에 있어야 함 |
| `webapp/lite_data.py` | 데이터 묶음 생성, 업로드, 내려받기, 설치 |
| `scripts/publish_lite_data.py` | 묶음을 만들어 올리는 실행 스크립트 |
| `scripts/publish_lite_data.md` | 위 스크립트 사용법 |
| `tests/test_lite_data.py` | 묶음, Parquet 일치 여부, 내려받기, 서버 진입점 테스트 |

### 배포를 위해 수정한 파일

| 파일 | 변경 |
|---|---|
| `web_app.py` | 서버 버전 메뉴와 표시 이름, 시작 시 데이터 동기화, 메뉴 번호 처리 변경 |
| `data_loader.py` | 주봉/월봉을 Parquet에서 종목별로 읽는 경로 추가. CSV 경로는 그대로 유지 |
| `webapp/data_status.py` | `web_app.py`의 데이터 현황 계산을 Streamlit 없이 쓰도록 분리 |
| `webapp/thumbnails.py` | 썸네일을 240px JPEG로 축소 |
| `.gitignore` | `/.app_data/lite_bundle/` 제외 |
| `README.md` | 경량 버전과 배포 안내 추가 |

### 배포 전에 먼저 적용한 경량 버전

| 파일 | 역할 |
|---|---|
| `web_app_lite.py` | 로컬 경량 버전 실행 파일. 색상을 명령줄 옵션으로 지정 |
| `webapp/theme_lite.css` | 터미널 색상. 배치와 간격은 `webapp/theme.css`를 공유 |
| `webapp/thumbnails.py` | 흰 배경 차트를 어둡게 뒤집은 썸네일 생성 |
| `tests/test_web_app_lite.py` | 메뉴 제외, 저장 기능 제외 테스트 |

경량 터미널 색상은 `web_app_lite.py`와 `lite/.streamlit/config.toml` 두 곳에 있습니다. 색을 바꿀 때는 둘 다 수정합니다.

## 4. 데이터 묶음

`scripts/publish_lite_data.py`가 다음을 `.app_data/lite_bundle/krx_lite_data.zip`으로 묶습니다. 첫 측정 크기는 120.3MB입니다.

| 묶음 내 경로 | 내용 |
|---|---|
| `data/master/kospi_tickers.csv` | 종목 마스터 |
| `data/lite/prices.parquet` | 마스터 종목의 주봉·월봉 (약 214만 행), KOSPI·KOSDAQ 지수 주봉 |
| `data/lite/manifest.json` | 생성 시각, 스캔 이름, 데이터 현황 |
| `output/scan_result_*/` | 최신 스캔 결과와 차트 PNG |

**포함하지 않는 것:** 일봉, 원시 시세, 로그, `tracking/`의 보유·관심·패턴 기록.

**동작 방식:**

- 업로드: 새 파일을 임시 이름으로 올린 뒤 기존 파일을 지우고 이름을 바꿉니다. 업로드에 실패해도 기존 파일이 남습니다.
- 내려받기: 앱이 1시간마다 Release를 확인하고, 파일 ID가 바뀐 경우에만 내려받습니다.
- 조회 실패: 기존 데이터가 있으면 그대로 쓰고, 없으면 오류 화면을 표시합니다.
- 코드 저장소에 넣지 않는 이유: 매일 100MB 이상이 이력에 쌓이고, 코드 저장소가 공개이기 때문입니다.

## 5. 서버 패키지

Streamlit Cloud 앱은 Python 3.14로 실행됩니다. 현재 `lite/requirements.txt`는 다음과 같습니다.

```text
streamlit==1.55.0
streamlit-image-select==0.6.0
pandas==2.3.3
numpy==2.4.3
pyarrow==23.0.1
matplotlib==3.10.8
mplfinance==0.12.10b0
pillow==12.3.0
requests==2.32.5
six==1.17.0
```

서버에서 쓰지 않는 `finance-datareader`는 넣지 않았습니다.

## 6. 처음 배포 절차

### 데이터 저장소와 토큰

1. GitHub에 비공개 저장소 `KRX_FDR_data`를 **README를 포함해** 만듭니다.
2. `KRX_FDR_data`에만 권한을 주는 fine-grained 토큰을 두 개 만듭니다.
   - 업로드용: Contents **Read and write**
   - 서버용: Contents **Read-only**
3. 이 PC의 사용자 환경변수에 다음을 설정하고 터미널을 다시 엽니다.
   - `KRX_DATA_REPO` = `hunjaecmu/KRX_FDR_data`
   - `KRX_DATA_TOKEN` = 업로드용 토큰

토큰은 코드나 문서, 대화에 적지 않습니다.

### 첫 업로드

```bat
python scripts/publish_lite_data.py
```

### Streamlit Cloud

1. [share.streamlit.io](https://share.streamlit.io)에서 **Create app**을 누릅니다.
2. 다음과 같이 입력하고, Secrets 없이 배포합니다.
   - Repository: `hunjaecmu/KRX_FDR`
   - Branch: `main`
   - Main file path: `lite/streamlit_app.py`
3. "KRX_DATA_REPO 설정이 없습니다" 화면이 나오는지 확인합니다.
4. **Sharing**에서 비공개로 바꾸고 볼 사람의 이메일을 초대합니다. 코드 저장소가 공개라서 앱은 기본적으로 공개입니다. 비공개 앱은 계정당 하나까지입니다.
5. **Secrets**에 다음을 입력합니다.

   ```toml
   KRX_DATA_REPO = "hunjaecmu/KRX_FDR_data"
   KRX_DATA_TOKEN = "서버용 읽기 토큰"
   ```

## 7. 매일 운영

```bat
python scripts/update_data.py
scan
```

- 전체 또는 경량 버전의 메뉴 1, 2번으로 해도 됩니다.
- 전체 데이터 업데이트와 스캔이 끝날 때마다 데이터 묶음을 자동으로 올립니다. 시장별 업데이트에서는 올리지 않습니다.
- 환경변수 `KRX_DATA_REPO`, `KRX_DATA_TOKEN`이 없으면 건너뜁니다. 켜 둔 앱은 환경변수를 설정한 뒤 재시작해야 합니다.
- 스캔 전 묶음에는 새 시세와 이전 스캔이 함께 들어가므로, 스캔까지 마쳐야 서버의 돌파 결과가 최신이 됩니다.
- 서버에는 업로드 후 최대 1시간 안에 반영됩니다.
- 토큰이 만료되면 업로드와 내려받기가 실패하니 만료일을 관리합니다.
- `main`에 푸시할 때마다 앱이 다시 빌드될 수 있으니, 코드는 `web/migration`에서 작업하고 묶어서 올립니다.

## 8. 배포 중 겪은 문제

| 증상 | 원인 | 조치 |
|---|---|---|
| 업로드 `HTTP 422 Repository is empty.` | 데이터 저장소에 커밋이 없어 Release 생성 불가 | README 커밋. 오류 시 GitHub 메시지가 보이도록 코드 수정 |
| `git add` 실패로 README만 커밋 (`ba339f64`) | `lite/` 안에 빈 `.git` 폴더가 있어 별도 저장소로 인식 | 빈 `.git`을 옮기고 나머지를 새 커밋(`19f8a00f`)으로 추가 |
| 서버 설치 실패 `RequiredDependencyException: zlib` | 앱이 Python 3.14이고 `pillow==11.1.0`에 3.14용 완성본이 없음 | `pillow==12.3.0`으로 변경 |
| 서버 실행 `ModuleNotFoundError` (`six.moves`) | `mplfinance`가 `six`를 쓰지만 의존성으로 선언하지 않음 | `six==1.17.0` 추가 |
| 시작화면 종목 수 0 (검증 중 발견) | 코드 분리 시 `pandas` import 누락을 포괄적 예외 처리가 숨김 | import 추가, 회귀 테스트 추가 |
| 썸네일 영역이 밝게 뒤집힘 (검증 중 발견) | 부품 내부는 CSS로 제어 불가 | 어두운 축소 이미지를 직접 생성 |

## 9. 검증 현황

### 확인한 것

- 빈 Python 3.14.10 환경에 `lite/requirements.txt`만 설치: 패키지 충돌 없음
- 같은 환경에서 자동 테스트 57개 통과. 서버에서 쓰지 않는 패키지가 필요한 테스트는 제외
- 같은 환경에서 빈 데이터 폴더로 시작해 내려받기, 돌파 종목 조회, 썸네일 클릭, 삼성전자 차트 조회 확인
- 42개 종목의 주봉·월봉 84건을 CSV와 Parquet로 비교해 차이 없음
- 실제 GitHub로 첫 업로드 성공 (사용자 확인)
- 이 PC의 전체 테스트 66개 통과

위 앱 실행 확인은 Windows에서 로컬 가짜 GitHub 서버를 사용했습니다.

### 아직 확인하지 못한 것

실제 서버에서 앱이 잘 실행된다는 것은 사용자가 확인했습니다. 다음 항목은 개별적으로 확인하지 못했습니다.

- 나눔 글꼴이 차트에 적용되는지
- 서버 메모리 한도 안에서 동작하는지
- 비공개 전환 후 초대하지 않은 사용자가 차단되는지

## 10. 알려진 한계

- 코드 저장소는 공개입니다. 비공개인 것은 앱과 데이터입니다.
- 서버 저장 공간은 재시작하면 사라질 수 있습니다. 그 경우 다음 접속 때 묶음을 다시 내려받습니다.
- 앱은 12시간 동안 접속이 없으면 잠듭니다.
- 큰 차트는 CSS로 어둡게 뒤집어, 상승과 하락 색이 원본보다 옅습니다.
- 썸네일의 강조 표시가 현재 종목과 다를 수 있습니다. 현재 위치는 차트 아래의 `4/155` 표시로 확인합니다.
- 시세를 공개로 재배포해도 되는지는 확인하지 못했습니다. 공개 전환 전에 데이터 제공처의 약관을 확인해야 합니다.
