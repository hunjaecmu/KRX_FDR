from __future__ import annotations

import glob
import os
from pathlib import Path
import sys

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import DATA_DIR
from data_store import update_one_raw_stock, generate_derived_for_one_stock
from market_scanner import scan_all_breakouts, save_scan_results_to_csv


def _has_placeholder_burst(raw_path: str) -> bool:
    try:
        df = pd.read_csv(raw_path)
    except Exception:
        return False

    required = {"date", "open", "high", "low", "close", "volume"}
    if df.empty or not required.issubset(df.columns):
        return False

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    if df.empty:
        return False

    tail = df.tail(60).copy()
    for col in ["open", "high", "low", "close", "volume"]:
        tail[col] = pd.to_numeric(tail[col], errors="coerce").fillna(0)

    placeholder = (
        tail["open"].eq(0)
        & tail["high"].eq(0)
        & tail["low"].eq(0)
        & tail["volume"].eq(0)
        & tail["close"].gt(0)
    )

    run = 0
    for val in placeholder.tolist():
        run = run + 1 if val else 0
        if run >= 3:
            return True
    return False


def _delete_symbol_files(code: str) -> None:
    for sub in ["raw/daily", "derived/daily", "derived/weekly", "derived/monthly"]:
        folder = os.path.join(DATA_DIR, *sub.split("/"))
        for path in glob.glob(os.path.join(folder, f"{code}_*.csv")):
            try:
                os.remove(path)
            except OSError:
                pass


def _copy_latest_all_breakouts_to_workspace(src_folder: str, workspace: Path) -> Path:
    src = Path(src_folder) / "all_breakouts.csv"
    dst = workspace / "all_breakouts.csv"
    if not src.exists():
        raise FileNotFoundError(src)
    dst.write_bytes(src.read_bytes())
    return dst


def _compare_with_mac(workspace: Path) -> None:
    mac_candidates = [workspace / "all_breakouts_mac.csv", workspace / "all_breakouts-mac.csv"]
    mac_path = next((p for p in mac_candidates if p.exists()), None)
    if mac_path is None:
        print("[COMPARE][WARN] mac 결과 파일(all_breakouts_mac.csv/all_breakouts-mac.csv) 없음")
        return

    win_path = workspace / "all_breakouts.csv"
    if not win_path.exists():
        print("[COMPARE][WARN] windows 결과 파일(all_breakouts.csv) 없음")
        return

    mac = pd.read_csv(mac_path, dtype={"code": str})
    win = pd.read_csv(win_path, dtype={"code": str})

    mac["code"] = mac["code"].astype(str).str.zfill(6)
    win["code"] = win["code"].astype(str).str.zfill(6)

    print(f"[COMPARE] mac_rows={len(mac)} win_rows={len(win)}")

    for side_name, df in [("mac", mac), ("win", win)]:
        counts = df.groupby("scan_case").size().sort_index()
        print(f"[COMPARE] case_counts_{side_name}:")
        for k, v in counts.items():
            print(f"  {k}={v}")

    mac_map = {(r.scan_case, r.code): r for r in mac.itertuples(index=False)}
    win_map = {(r.scan_case, r.code): r for r in win.itertuples(index=False)}

    only_mac = sorted(set(mac_map.keys()) - set(win_map.keys()))
    only_win = sorted(set(win_map.keys()) - set(mac_map.keys()))

    print(f"[COMPARE] only_mac={len(only_mac)} only_win={len(only_win)}")

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


def main() -> None:
    workspace = ROOT_DIR

    master = pd.read_csv(os.path.join(DATA_DIR, "master", "kospi_tickers.csv"), dtype={"code": str})
    master["code"] = master["code"].astype(str).str.zfill(6)
    name_map = dict(zip(master["code"], master["name"]))

    raw_dir = os.path.join(DATA_DIR, "raw", "daily")
    candidates: list[str] = []

    for path in glob.glob(os.path.join(raw_dir, "*_*.csv")):
        code = os.path.basename(path)[:6]
        if code in name_map and _has_placeholder_burst(path):
            candidates.append(code)

    candidates = sorted(set(candidates))
    print(f"[REFRESH] candidate_count={len(candidates)}")

    refreshed = []
    for i, code in enumerate(candidates, start=1):
        _delete_symbol_files(code)
        raw_res = update_one_raw_stock(code, name_map[code])
        der_res = generate_derived_for_one_stock(code, name_map[code])
        refreshed.append({
            "code": code,
            "name": name_map[code],
            "raw_status": raw_res.get("status"),
            "raw_rows": raw_res.get("rows", 0),
            "derived_status": der_res.get("status"),
        })
        if i % 20 == 0 or i == len(candidates):
            print(f"[REFRESH] progress={i}/{len(candidates)}")

    refreshed_df = pd.DataFrame(refreshed)
    refreshed_df.to_csv(workspace / "placeholder_refresh_result.csv", index=False, encoding="utf-8-sig")

    if not refreshed_df.empty:
        summary = refreshed_df.groupby(["raw_status", "derived_status"]).size().reset_index(name="count")
        print("[REFRESH] summary")
        print(summary.to_string(index=False))

    # Step 3: rescan and compare with mac result
    results = scan_all_breakouts()
    saved_folder = save_scan_results_to_csv(results)
    print(f"[SCAN] saved_folder={saved_folder}")

    copied = _copy_latest_all_breakouts_to_workspace(saved_folder, workspace)
    print(f"[SCAN] copied_to={copied}")

    _compare_with_mac(workspace)


if __name__ == "__main__":
    main()
