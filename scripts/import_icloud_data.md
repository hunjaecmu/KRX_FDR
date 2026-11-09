# scripts/import_icloud_data.py

Mac이 iCloud Drive에 올린 데이터 묶음(`krx_full_data.zip`)을 PC 데이터에 합치는 스크립트 문서입니다. PC에서 직접 시세를 받거나 스캔하지 않고 Mac의 결과를 가져올 때 씁니다.

## 1. 역할 요약

- 기본 경로는 `D:\iCloud Drive\iCloudDrive\KRX_FDR\krx_full_data.zip`입니다. 환경변수 `KRX_ICLOUD_ZIP`이나 첫 번째 인자로 바꿀 수 있습니다.
- 묶음 안의 `manifest.json`으로 KRX_FDR 데이터인지 확인합니다. `built_at`이 지난번에 가져온 묶음과 같으면 건너뜁니다 (`--force`로 다시 합치기).
- 일봉 원본(`data/raw/daily`)은 파일을 통째로 덮어쓰지 않고 날짜 단위로 합칩니다.
  - 묶음에 있는 날짜는 Mac 값을 씁니다.
  - PC에만 있는 더 오래된 이력은 남깁니다.
  - 겹치는 앞부분 종가가 1% 넘게 다르면 액면분할, 분배금 등으로 과거 가격이 수정된 것으로 보고 Mac 파일로 교체합니다.
  - 이름이 바뀐 종목은 마스터의 현재 이름 파일을 씁니다.
- 바뀐 종목만 파생 데이터(일봉·주봉·월봉 이평)를 다시 만듭니다.
- 종목 마스터, 지수 파일을 묶음의 것으로 바꾸고, 스캔 결과 폴더(`output/scan_result_*`)가 없으면 복사합니다.
- 끝나면 서버용 데이터 묶음을 자동 업로드합니다 (`webapp/auto_publish.py`, 환경변수가 있을 때).
- 가져온 묶음 정보는 `.app_data/data/logs/icloud_import.json`에 남깁니다.

## 2. 실행 예시

```bash
python scripts/import_icloud_data.py
```

Windows에서는 프로젝트 폴더의 `import_icloud.cmd`로 실행합니다. 출력은 `.app_data/data/logs/icloud_import.log`에 쌓입니다. 작업 스케줄러의 `KRX_FDR iCloud 데이터 가져오기` 작업이 월~금 21:30에 이 파일을 실행합니다.

## 3. 의존성

- data_store.py
- webapp/auto_publish.py
