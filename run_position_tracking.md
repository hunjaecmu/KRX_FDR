# run_position_tracking.py

포지션 트래킹 단독 실행 엔트리 문서입니다.

## 1. 역할 요약

`run_position_tracking.py`는 `position_tracker.run_position_tracking()`를 호출하고, 결과를 사람이 읽기 쉬운 콘솔 로그로 출력합니다.

## 2. 실행 흐름

`main()`:

1. `run_position_tracking()` 호출
2. 결과 상태 확인
   - 성공(`status == ok`):
     - rows
     - snapshot_file
     - history_file
   - 실패/스킵:
     - status
     - message
     - 입력 CSV 경로

## 3. 사용 시점

- 스캔 전체를 돌리지 않고 포지션 리포트만 만들고 싶을 때
- 보유/관심 목록 CSV가 잘 읽히는지 빠르게 점검할 때

## 4. 사용 예시

```bash
python run_position_tracking.py
```

## 5. 의존성

- position_tracker.py
- config.py (입력/출력 경로)
