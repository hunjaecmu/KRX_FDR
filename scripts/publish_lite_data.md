# scripts/publish_lite_data.py

Streamlit Community Cloud에 배포한 경량 버전이 사용할 데이터 묶음을 만들어 올리는 스크립트 문서입니다.

## 1. 역할

- 최신 스캔 결과, 종목 마스터, 주봉/월봉(Parquet)을 `krx_lite_data.zip`으로 묶음
- 데이터 저장소 GitHub Release의 `lite-data` 태그에 올려 기존 파일과 교체
- 서버 앱은 시작 후 1시간마다 새 묶음을 확인해 내려받음

## 2. 준비

- 데이터 전용 비공개 저장소 생성
- 그 저장소의 Contents 읽기/쓰기 권한만 가진 fine-grained 토큰 발급
- 이 PC의 환경변수 `KRX_DATA_REPO`(`owner/name`), `KRX_DATA_TOKEN` 설정

## 3. 실행

전체 업데이트와 스캔을 마친 뒤 실행합니다.

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
