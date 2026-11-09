# scripts/nightly_summary.py
"""저녁 자동 스캔(scripts/mac/nightly_scan.sh)이 끝난 뒤 보낼 알림 문구를 만든다.

    python scripts/nightly_summary.py --started 1730900000 --update ok --scan ok --publish ok --share ok
"""

import argparse
import glob
import json
import os
import sys
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd  # noqa: E402

from config import DATA_DIR, OUTPUT_DIR  # noqa: E402

WEEKDAYS = "월화수목금토일"
STEP_LABELS = [
    ("update", "데이터 업데이트"),
    ("scan", "이평 돌파 스캔"),
    ("publish", "GitHub 묶음 업로드"),
    ("share", "iCloud 전체 데이터"),
]
STATUS_TEXT = {"ok": "완료", "fail": "실패", "skip": "건너뜀"}
SHORT_LABELS = {
    "weekly_ma10_breakout": "주봉10",
    "weekly_ma240_breakout": "주봉240",
    "monthly_ma10_breakout": "월봉10",
    "monthly_ma120_breakout": "월봉120",
    "monthly_ma180_breakout": "월봉180",
    "monthly_ma240_breakout": "월봉240",
}


def _newest(pattern: str, since: float):
    files = [f for f in glob.glob(pattern) if os.path.getmtime(f) >= since]
    return max(files, key=os.path.getmtime) if files else None


def update_line(since: float) -> str:
    path = _newest(os.path.join(DATA_DIR, "logs", "raw_update_result_*.csv"), since)
    if not path:
        return ""
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    counts = df["status"].value_counts().to_dict()
    failed = sum(v for k, v in counts.items() if k not in {"skip", "incr", "init"})
    updated = counts.get("incr", 0) + counts.get("init", 0)
    line = f"종목 {len(df):,}개 중 갱신 {updated:,}"
    if failed:
        line += f" · 실패 {failed:,}"
    return line


def scan_lines(since: float) -> list[str]:
    scans = sorted(glob.glob(os.path.join(OUTPUT_DIR, "scan_result_*")))
    if not scans or os.path.getmtime(scans[-1]) < since:
        return []
    summary = os.path.join(scans[-1], "summary.csv")
    if not os.path.exists(summary):
        return []
    df = pd.read_csv(summary, encoding="utf-8-sig")
    parts = [f"{SHORT_LABELS.get(r.scan_case, r.scan_label)} {int(r['count'])}" for _, r in df.iterrows()]
    return ["돌파: " + " · ".join(parts[:3]), "      " + " · ".join(parts[3:])] if len(parts) > 3 else ["돌파: " + " · ".join(parts)]


def share_size() -> str:
    share_dir = os.getenv("KRX_SHARE_DIR") or os.path.join(
        os.path.expanduser("~"), "Library", "Mobile Documents", "com~apple~CloudDocs", "KRX_FDR"
    )
    try:
        with open(os.path.join(share_dir, "krx_full_data.json"), encoding="utf-8") as f:
            return f" ({json.load(f).get('size_mb')}MB)"
    except (OSError, ValueError):
        return ""


def build_message(args) -> str:
    started = float(args.started)
    statuses = {key: getattr(args, key) for key, _ in STEP_LABELS}
    all_ok = all(v == "ok" for v in statuses.values())
    now = datetime.now()
    minutes = max(1, round((now.timestamp() - started) / 60))

    head = "✅ KRX 스캔 완료" if all_ok else "⚠️ KRX 스캔 문제 발생"
    lines = [f"{head} ({now:%m/%d}({WEEKDAYS[now.weekday()]}) {now:%H:%M}, {minutes}분)"]

    upd = update_line(started)
    if upd:
        lines.append(upd)
    lines += scan_lines(started)

    for key, label in STEP_LABELS:
        status = statuses[key]
        if key == "share" and status == "ok":
            lines.append(f"{label}: 저장 완료{share_size()}")
        elif status != "ok" or not all_ok:
            lines.append(f"{label}: {STATUS_TEXT.get(status, status)}")
        elif key == "publish":
            lines.append(f"{label}: 완료")

    if not all_ok and args.log:
        lines.append(f"로그: {args.log}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="저녁 자동 스캔 알림 문구를 출력합니다.")
    parser.add_argument("--started", required=True, help="작업 시작 시각 (epoch 초)")
    for key, _ in STEP_LABELS:
        parser.add_argument(f"--{key}", default="skip", choices=["ok", "fail", "skip"])
    parser.add_argument("--log", default="")
    print(build_message(parser.parse_args()))


if __name__ == "__main__":
    main()
