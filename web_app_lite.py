"""조회 전용 경량 버전 실행 파일: python web_app_lite.py [streamlit 옵션]"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

TERMINAL_THEME = {
    "base": "dark",
    "primaryColor": "#d29922",
    "backgroundColor": "#0d1117",
    "secondaryBackgroundColor": "#161b22",
    "textColor": "#e6edf3",
    "borderColor": "#30363d",
    "dataframeBorderColor": "#30363d",
    "dataframeHeaderBackgroundColor": "#161b22",
    "linkColor": "#58a6ff",
    "baseRadius": "4px",
    "sidebar.backgroundColor": "#010409",
    "sidebar.secondaryBackgroundColor": "#161b22",
}


def build_command(extra_args: list[str]) -> list[str]:
    command = [sys.executable, "-m", "streamlit", "run", os.path.join(ROOT, "web_app.py"), "--server.port", "8502"]
    command += [f"--theme.{key}={value}" for key, value in TERMINAL_THEME.items()]
    return command + extra_args


if __name__ == "__main__":
    # 프로젝트 폴더의 .streamlit/config.toml을 읽고 색상만 위 값으로 덮어쓴다.
    env = dict(os.environ, KRX_APP_EDITION="lite")
    raise SystemExit(subprocess.call(build_command(sys.argv[1:]), cwd=ROOT, env=env))
