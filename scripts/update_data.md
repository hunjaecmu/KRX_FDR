# scripts/update_data.py

데이터 수집/파생 생성 배치를 실행하는 래퍼 스크립트 문서입니다.

## 1. 역할 요약

`update_data.py`는 `data_store.run_all(...)`을 호출하여 데이터 업데이트를 수행합니다.

현재 파라미터:

- `force_master_update=False`
- `derive_all=True`

즉, 마스터는 조건부 갱신하고, 파생 데이터는 전체 종목 기준으로 재생성합니다. KOSPI, KOSDAQ 지수도 함께 갱신합니다.

진행 순서:

1. 수집: 종목마다 마지막으로 확정 저장한 종가의 다음 날부터 오늘까지 받습니다. 이 단계에서는 종목 파일을 바꾸지 않습니다.
   - 이미 확정 저장한 종가는 다시 받거나 비교하지 않습니다. 20:00 전에 받아 장중으로 저장된 봉만 다음 실행 때 다시 받습니다.
   - 실패한 종목은 끝에 한 번 더 시도합니다. 그래도 실패하면 그 종목만 빼고 진행합니다.
2. 일일 시세 파일: 새로 받은 시세, 종목 목록, 시장 지수를 `data/daily_close/YYYYMMDD_HHMMSS.zip` 하나에 저장합니다. 60일 보관합니다.
3. 반영: 일일 시세 파일의 내용을 종목 파일(`data/raw/daily`)에 반영하고 파생 데이터를 만듭니다.

다른 PC는 이 일일 시세 파일만 받아 같은 방식으로 반영합니다 (`scripts/share_full_data.py`, `pull.cmd`).

끝나면 서버용 데이터 묶음을 자동 업로드합니다 (`webapp/auto_publish.py`, 환경변수가 있을 때).

## 2. 실행 예시

```bash
python scripts/update_data.py
```

Windows cmd에서는 프로젝트 폴더의 `update.cmd`로, macOS에서는 `update.command`(Finder에서 더블클릭 또는 `./update.command`)로 같은 업데이트를 실행합니다. 스캔(`scan.cmd`, macOS는 `scan.command`)은 시세를 받지 않으므로, 업데이트를 먼저 실행한 뒤 스캔합니다.

```bat
update
```

## 3. 콘솔 출력

- 실행 시작/완료 메시지
- 내부적으로 `run_all`의 진행 로그 및 요약 로그 출력

## 4. 의존성

- data_store.py
- webapp/auto_publish.py
