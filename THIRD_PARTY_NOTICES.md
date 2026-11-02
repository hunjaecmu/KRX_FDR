이 앱은 아래 오픈소스 소프트웨어와 글꼴을 사용합니다. 각 항목의 저작권은 해당 저작권자에게 있으며, 각 라이선스의 조건을 따릅니다.

## 소프트웨어

| 이름 | 버전 | 라이선스 | 사용 위치 |
|---|---|---|---|
| [Streamlit](https://streamlit.io) | 1.55.0 | Apache-2.0 | 웹 화면 |
| [streamlit-image-select](https://github.com/jrieke/streamlit-image-select) | 0.6.0 | MIT | 차트 썸네일 선택 |
| [pandas](https://pandas.pydata.org) | 2.3.3 | BSD-3-Clause | 데이터 처리 |
| [NumPy](https://numpy.org) | 2.4.3 | BSD-3-Clause 외 (0BSD, MIT, Zlib, CC0-1.0) | 수치 계산 |
| [Apache Arrow (pyarrow)](https://arrow.apache.org) | 23.0.1 | Apache-2.0 | Parquet 데이터 읽기·쓰기 |
| [Matplotlib](https://matplotlib.org) | 3.10.8 | Matplotlib License (PSF 계열) | 차트 |
| [mplfinance](https://github.com/matplotlib/mplfinance) | 0.12.10b0 | BSD 계열 | 캔들 차트 |
| [Pillow](https://python-pillow.github.io) | 12.3.0 | MIT-CMU | 썸네일 이미지 처리 |
| [Requests](https://requests.readthedocs.io) | 2.32.5 | Apache-2.0 | 데이터 내려받기 |
| [six](https://github.com/benjaminp/six) | 1.17.0 | MIT | mplfinance 호환 |
| [FinanceDataReader](https://github.com/FinanceData/FinanceDataReader) | 0.9.110 | MIT | 시세 수집 (로컬 수집 단계에서만 사용) |

위 패키지가 의존하는 다른 패키지는 각 패키지의 라이선스를 따르며, 이 목록에는 직접 사용하는 패키지만 적었습니다.

## 글꼴과 아이콘

| 이름 | 라이선스 | 사용 위치 |
|---|---|---|
| [Pretendard](https://github.com/orioncactus/pretendard) | SIL Open Font License | 화면 글꼴 (jsDelivr CDN) |
| [나눔 글꼴](https://hangeul.naver.com/font) | SIL Open Font License | 차트 한글 (서버 설치) |
| [Material Symbols](https://fonts.google.com/icons) | Apache-2.0 | 메뉴 아이콘 (Streamlit 내장) |

## 데이터

시세는 FinanceDataReader를 통해 수집합니다. 위 소프트웨어 라이선스는 프로그램에 적용되며, 시세 데이터의 권리와 이용 조건은 각 데이터 제공처에 따릅니다.

## 면책

- 위 오픈소스는 각 라이선스에 따라 "있는 그대로" 제공되며, 저작권자는 이 앱의 결과에 책임지지 않습니다.
- 이 앱의 정보는 참고용이며 투자 권유가 아닙니다. 데이터의 정확성과 최신성을 보장하지 않으며, 투자 판단과 그 결과에 대한 책임은 이용자에게 있습니다.
- 각 제품명과 상표는 해당 소유자의 자산입니다.
