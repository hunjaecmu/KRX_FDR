#!/bin/bash
# macOS용 실행기 (Windows의 scan.cmd와 같은 역할). Finder에서 더블클릭하거나 터미널에서 ./scan.command 로 실행.
cd "$(dirname "$0")" || exit 1
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; else PY="python3"; fi
"$PY" -u scripts/scan_market.py "$@"
