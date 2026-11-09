#!/bin/bash
# 공유 폴더(iCloud Drive)의 일일 시세 파일을 반영하고 스캔 (Windows의 pull.cmd와 같은 역할)
cd "$(dirname "$0")" || exit 1
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; else PY="python3"; fi
"$PY" -u scripts/share_full_data.py import "$@"
