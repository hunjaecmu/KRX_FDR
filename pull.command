#!/bin/bash
# 공유 폴더(iCloud Drive)의 전체 데이터를 이 Mac에 설치 (Windows의 pull.cmd와 같은 역할)
cd "$(dirname "$0")" || exit 1
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; else PY="python3"; fi
"$PY" -u scripts/share_full_data.py import "$@"
