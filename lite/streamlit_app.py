"""Streamlit Community Cloud 진입점: 조회 전용 서버 버전으로 web_app.py를 실행한다."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_APP_PATH = os.path.join(ROOT, "web_app.py")

os.environ["KRX_APP_EDITION"] = "cloud"
os.environ["KRX_DATA_SOURCE"] = "parquet"
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

__file__ = WEB_APP_PATH
with open(WEB_APP_PATH, encoding="utf-8") as _web_app_file:
    exec(compile(_web_app_file.read(), WEB_APP_PATH, "exec"))
