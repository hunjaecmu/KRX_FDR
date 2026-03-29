from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from market_scanner import scan_all_breakouts, save_scan_results_to_csv


def main() -> None:
    workspace = ROOT_DIR

    results = scan_all_breakouts()
    save_folder = save_scan_results_to_csv(results)
    print(f"[SCAN] saved_folder={save_folder}")

    src = Path(save_folder) / "all_breakouts.csv"
    dst = workspace / "all_breakouts.csv"
    dst.write_bytes(src.read_bytes())
    print(f"[SCAN] copied={dst}")

    mac_path = workspace / "all_breakouts_mac.csv"
    if not mac_path.exists():
        alt = workspace / "all_breakouts-mac.csv"
        if alt.exists():
            mac_path = alt
        else:
            print("[COMPARE][WARN] mac file not found")
            return

    win = pd.read_csv(dst, dtype={"code": str})
    mac = pd.read_csv(mac_path, dtype={"code": str})

    win["code"] = win["code"].astype(str).str.zfill(6)
    mac["code"] = mac["code"].astype(str).str.zfill(6)

    print(f"[COMPARE] rows mac={len(mac)} win={len(win)}")

    print("[COMPARE] case counts mac")
    for k, v in mac.groupby("scan_case").size().sort_index().items():
        print(f"  {k}={v}")

    print("[COMPARE] case counts win")
    for k, v in win.groupby("scan_case").size().sort_index().items():
        print(f"  {k}={v}")

    mac_keys = set(zip(mac["scan_case"], mac["code"]))
    win_keys = set(zip(win["scan_case"], win["code"]))

    only_mac = sorted(mac_keys - win_keys)
    only_win = sorted(win_keys - mac_keys)

    print(f"[COMPARE] only_mac={len(only_mac)} only_win={len(only_win)}")

    mac_map = {(r.scan_case, r.code): r for r in mac.itertuples(index=False)}
    win_map = {(r.scan_case, r.code): r for r in win.itertuples(index=False)}

    only_mac_rows = []
    for scan_case, code in only_mac:
        r = mac_map[(scan_case, code)]
        only_mac_rows.append({
            "scan_case": scan_case,
            "code": code,
            "name": r.name,
            "date": r.date,
            "close": r.close,
            "ma_value": r.ma_value,
            "breakout_pct": r.breakout_pct,
            "is_final": r.is_final,
        })

    only_win_rows = []
    for scan_case, code in only_win:
        r = win_map[(scan_case, code)]
        only_win_rows.append({
            "scan_case": scan_case,
            "code": code,
            "name": r.name,
            "date": r.date,
            "close": r.close,
            "ma_value": r.ma_value,
            "breakout_pct": r.breakout_pct,
            "is_final": r.is_final,
        })

    pd.DataFrame(only_mac_rows).to_csv(workspace / "diff_only_mac_after_refresh.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(only_win_rows).to_csv(workspace / "diff_only_win_after_refresh.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
