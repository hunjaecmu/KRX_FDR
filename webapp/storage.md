# webapp/storage.py

웹 앱의 CSV 읽기/쓰기를 담당하는 모듈 문서입니다. Streamlit에 의존하지 않습니다.

## 1. 역할 요약

- 관심종목, 패턴 기록, 보유 종목 CSV 읽기/쓰기
- 월별 관심종목 파일 경로와 패턴 기록 파일 옵션 관리
- 보유 CSV 컬럼 자동 인식(`pick_column`)과 행 추가(`add_holding_row`)

## 2. 데이터 보호 규칙

- `read_csv`: `utf-8-sig`, `cp949` 순서로 읽고, 읽지 못하면 `CsvReadError` 발생
  - 내용이 없는 파일(0바이트)은 빈 DataFrame 반환
- `append_row`, `add_holding_row`: 기존 파일을 읽지 못하면 저장하지 않고 예외 발생
- `write_csv`:
  - 기존 파일을 `_backup/{파일명}_{시각}.csv`로 복사한 뒤 저장 (파일별 최근 30개 유지)
  - 임시 파일에 쓴 뒤 교체하므로 저장 실패 시 원본 유지
  - 항상 `utf-8-sig`로 저장

## 3. 테스트

```bash
python -m unittest discover -s tests
```
