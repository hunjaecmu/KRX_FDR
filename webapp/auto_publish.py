"""데이터 업데이트와 스캔이 끝난 뒤 서버용 데이터 묶음을 자동으로 올린다."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLISH_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "publish_lite_data.py")
ALL_MARKETS = {"KOSPI", "KOSDAQ", "ETF"}


def is_full_update(markets: Optional[list[str]]) -> bool:
    return not markets or {str(m).upper() for m in markets} == ALL_MARKETS


def publish_after(step: str) -> bool:
    """묶음을 올리고 성공 여부를 돌려준다. 실패해도 앞선 작업을 실패로 만들지 않는다."""
    if not (os.getenv("KRX_DATA_REPO") and os.getenv("KRX_DATA_TOKEN")):
        print(f"[PUBLISH] {step} 완료: KRX_DATA_REPO/KRX_DATA_TOKEN 설정이 없어 업로드를 건너뜁니다.", flush=True)
        return False

    print(f"[PUBLISH] {step} 완료: 데이터 묶음 업로드 시작", flush=True)
    # 앞선 작업의 메모리를 쓰지 않도록 별도 프로세스로 실행한다.
    try:
        return_code = subprocess.call([sys.executable, "-u", PUBLISH_SCRIPT], cwd=PROJECT_ROOT)
    except OSError as e:
        print(f"[PUBLISH][WARN] 업로드 실행 실패: {e}", flush=True)
        return False

    if return_code != 0:
        print(f"[PUBLISH][WARN] 업로드 실패 (종료 코드 {return_code}). 서버는 이전 데이터를 유지합니다.", flush=True)
        return False
    return True
