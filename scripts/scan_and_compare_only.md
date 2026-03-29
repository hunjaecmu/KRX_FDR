# scripts/scan_and_compare_only.py

재스캔 후 Mac/Windows 결과 차이만 비교하는 경량 스크립트 문서입니다.

## 1. 역할 요약

`scan_and_compare_only.py`는 데이터 재생성 없이 다음만 수행합니다.

1. 전체 스캔 실행
2. 최신 `all_breakouts.csv`를 워크스페이스 루트로 복사
3. Mac 결과 파일(`all_breakouts_mac.csv` 또는 `all_breakouts-mac.csv`)과 비교
4. 차이 CSV 저장

## 2. 생성 파일

- `all_breakouts.csv`
- `diff_only_mac_after_refresh.csv`
- `diff_only_win_after_refresh.csv`

## 3. 비교 기준

- 키: `(scan_case, code)`
- 양쪽에만 존재하는 종목을 각각 파일로 분리 저장

## 4. 실행 예시

```bash
python scripts/scan_and_compare_only.py
```

## 5. 의존성

- market_scanner.py
- pandas
