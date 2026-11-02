# scripts/update_data.py

import os
import sys

# Ensure project root is importable when this script is executed directly.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_store import run_all

if __name__ == "__main__":
    print("데이터 업데이트 시작")
    run_all(
        force_master_update=False,
        derive_all=True
    )
    print("데이터 업데이트 완료")