# scripts/update_data.py

데이터 수집/파생 생성 배치를 실행하는 래퍼 스크립트 문서입니다.

## 1. 역할 요약

`update_data.py`는 `data_store.run_all(...)`을 호출하여 데이터 업데이트를 수행합니다.

현재 파라미터:

- `force_master_update=False`
- `derive_all=True`

즉, 마스터는 조건부 갱신하고, 파생 데이터는 전체 종목 기준으로 재생성합니다.

## 2. 실행 예시

```bash
python scripts/update_data.py
```

## 3. 콘솔 출력

- 실행 시작/완료 메시지
- 내부적으로 `run_all`의 진행 로그 및 요약 로그 출력

## 4. 의존성

- data_store.py
