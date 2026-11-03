# scripts/publish_lite_data.py

Streamlit Community Cloud에 배포한 경량 버전이 사용할 데이터 묶음을 만들어 올리는 스크립트 문서입니다.

## 1. 역할

- 최신 스캔 결과, 종목 마스터, 종목과 지수의 주봉/월봉(Parquet), 지수 요약을 `krx_lite_data.zip`으로 묶음
- 보유·관심·패턴 기록은 포함하지 않음
- 데이터 저장소 GitHub Release의 `lite-data` 태그에 올려 기존 파일과 교체
- 서버 앱은 시작 후 1시간마다 새 묶음을 확인해 내려받음

## 2. 준비

- 데이터 전용 비공개 저장소 생성
- 그 저장소의 Contents 읽기/쓰기 권한만 가진 fine-grained 토큰 발급
- 이 PC의 환경변수 `KRX_DATA_REPO`(`owner/name`), `KRX_DATA_TOKEN` 설정

## 3. 실행

다음 작업이 성공적으로 끝나면 자동으로 실행됩니다.

- 전체 데이터 업데이트 (웹 앱의 전체 업데이트, `update.cmd`, `scripts/update_data.py`)
- 스캔 (웹 앱의 2번 메뉴, `scan.cmd`, `scripts/scan_market.py`)

`run_evening_scan.py`에서는 자동으로 실행되지 않습니다.

시장별 업데이트에서는 실행되지 않습니다. 환경변수가 없으면 건너뛰고, 업로드에 실패해도 앞선 작업은 성공으로 끝납니다.

직접 실행하려면:

```bash
python scripts/publish_lite_data.py
```

묶음만 만들어 확인하려면:

```bash
python scripts/publish_lite_data.py --build-only
```

## 4. 서버 설정

Streamlit Cloud의 Secrets에 다음을 입력합니다. 서버 앱에는 읽기 전용 토큰을 권장합니다.

```toml
KRX_DATA_REPO = "owner/name"
KRX_DATA_TOKEN = "토큰"
```
