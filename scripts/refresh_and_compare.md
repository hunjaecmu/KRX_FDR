# scripts/refresh_and_compare.py

placeholder 패턴 종목을 재생성하고, 재스캔 후 Mac 결과와 비교하는 유틸 스크립트 문서입니다.

## 1. 역할 요약

`refresh_and_compare.py`는 검증/정합성 확인 목적의 운영 보조 스크립트입니다.

주요 단계:

1. placeholder burst 종목 탐지
2. 대상 종목 raw/derived 파일 삭제 후 재수집/재생성
3. 전체 스캔 재실행
4. Mac 결과 파일과 차이 비교
5. 차이 CSV 저장

## 2. placeholder 판정

`_has_placeholder_burst`:

- 최근 60개 raw 행에서
- `open=0, high=0, low=0, volume=0, close>0` 조건이
- 3개 이상 연속이면 후보로 판정

## 3. 생성 파일

워크스페이스 루트에 아래 파일을 생성할 수 있습니다.

- `placeholder_refresh_result.csv`
- `all_breakouts.csv`
- `diff_only_mac_after_refresh.csv`
- `diff_only_win_after_refresh.csv`

## 4. 실행 예시

```bash
python scripts/refresh_and_compare.py
```

## 5. 주의사항

- raw/derived 파일을 삭제 후 재생성하므로 실행 시간이 길 수 있습니다.
- 비교용 임시 CSV를 루트에 생성합니다.

## 6. 의존성

- config.py
- data_store.py
- market_scanner.py
- pandas
