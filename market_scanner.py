# market_scanner.py

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

import pandas as pd

from config import OUTPUT_DIR
from data_loader import load_master, load_weekly, load_monthly


SCAN_CASES = {
    "weekly_ma10_breakout": {
        "timeframe": "weekly",
        "ma_col": "ma10",
        "label": "주봉 10이평 돌파",
    },
    "weekly_ma240_breakout": {
        "timeframe": "weekly",
        "ma_col": "ma240",
        "label": "주봉 240이평 돌파",
    },
    "monthly_ma10_breakout": {
        "timeframe": "monthly",
        "ma_col": "ma10",
        "label": "월봉 10이평 돌파",
    },
    "monthly_ma120_breakout": {
        "timeframe": "monthly",
        "ma_col": "ma120",
        "label": "월봉 120이평 돌파",
    },
}


def _load_by_timeframe(code: str, timeframe: str) -> pd.DataFrame:
    if timeframe == "weekly":
        return load_weekly(code)
    if timeframe == "monthly":
        return load_monthly(code)
    raise ValueError(f"지원하지 않는 timeframe: {timeframe}")


def detect_breakout_up(df: pd.DataFrame, ma_col: str) -> Optional[dict]:
    """
    상향 돌파 조건:
      이전 봉 close <= 이전 봉 MA
      현재 봉 close > 현재 봉 MA
    """
    if df is None or len(df) < 2:
        return None

    required = {"date", "close", ma_col}
    if not required.issubset(df.columns):
        return None

    recent = df.dropna(subset=["close", ma_col]).copy()
    if len(recent) < 2:
        return None

    prev_row = recent.iloc[-2]
    curr_row = recent.iloc[-1]

    prev_close = float(prev_row["close"])
    prev_ma = float(prev_row[ma_col])
    curr_close = float(curr_row["close"])
    curr_ma = float(curr_row[ma_col])

    crossed = (prev_close <= prev_ma) and (curr_close > curr_ma)
    if not crossed:
        return None

    strength = (curr_close / curr_ma) - 1.0 if curr_ma != 0 else None

    return {
        "date": pd.to_datetime(curr_row["date"]),
        "close": curr_close,
        "ma_value": curr_ma,
        "prev_close": prev_close,
        "prev_ma_value": prev_ma,
        "breakout_strength": strength,
        "is_final": curr_row["is_final"] if "is_final" in curr_row.index else None,
    }


def scan_one_case(case_key: str, timeframe: str, ma_col: str, label: str) -> list[dict]:
    master = load_master()
    rows: list[dict] = []

    for row in master.itertuples(index=False):
        code = str(row.code).zfill(6)
        name = str(row.name)

        try:
            df = _load_by_timeframe(code, timeframe)
            info = detect_breakout_up(df, ma_col)
            if info is None:
                continue

            rows.append({
                "scan_case": case_key,
                "scan_label": label,
                "timeframe": timeframe,
                "ma_col": ma_col,
                "code": code,
                "name": name,
                "date": pd.to_datetime(info["date"]).strftime("%Y-%m-%d"),
                "close": info["close"],
                "ma_value": info["ma_value"],
                "prev_close": info["prev_close"],
                "prev_ma_value": info["prev_ma_value"],
                "breakout_strength": info["breakout_strength"],
                "breakout_pct": info["breakout_strength"] * 100 if info["breakout_strength"] is not None else None,
                "is_final": info["is_final"],
            })

        except Exception as e:
            print(f"[SCAN][WARN] {timeframe} {code} {name}: {e}")
            continue

    rows.sort(
        key=lambda x: (-999999 if x["breakout_strength"] is None else -x["breakout_strength"], x["code"])
    )
    return rows


def scan_all_breakouts() -> dict[str, list[dict]]:
    results: dict[str, list[dict]] = {}

    for case_key, meta in SCAN_CASES.items():
        results[case_key] = scan_one_case(
            case_key=case_key,
            timeframe=meta["timeframe"],
            ma_col=meta["ma_col"],
            label=meta["label"],
        )

    return results


def print_scan_results(results: dict[str, list[dict]]) -> None:
    for case_key, items in results.items():
        label = SCAN_CASES[case_key]["label"]
        print(f"\n[{label}] {len(items)}개")

        for i, item in enumerate(items, start=1):
            strength_pct = item["breakout_pct"]
            strength_text = f"{strength_pct:.2f}%" if strength_pct is not None else "N/A"

            print(
                f"{i:>3}. {item['code']} {item['name']} | "
                f"date={item['date']} | "
                f"close={item['close']:.2f} | "
                f"{item['ma_col']}={item['ma_value']:.2f} | "
                f"strength={strength_text} | "
                f"is_final={item['is_final']}"
            )


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def save_scan_results_to_csv(
    results: dict[str, list[dict]],
    output_root: str | None = None,
    timestamp: str | None = None,
) -> str:
    """
    저장 구조:
      output/scan_result_YYYYMMDD_HHMMSS/
        - all_breakouts.csv
        - summary.csv
        - weekly_ma10_breakout.csv
        - weekly_ma240_breakout.csv
        - monthly_ma10_breakout.csv
        - monthly_ma120_breakout.csv
    """
    if output_root is None:
        output_root = OUTPUT_DIR

    if timestamp is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    folder = os.path.join(output_root, f"scan_result_{timestamp}")
    _ensure_dir(folder)

    all_rows = []
    summary_rows = []

    for case_key, items in results.items():
        df_case = pd.DataFrame(items)

        case_file = os.path.join(folder, f"{case_key}.csv")
        if df_case.empty:
            df_case = pd.DataFrame(columns=[
                "scan_case", "scan_label", "timeframe", "ma_col",
                "code", "name", "date",
                "close", "ma_value", "prev_close", "prev_ma_value",
                "breakout_strength", "breakout_pct", "is_final",
            ])
        else:
            df_case = df_case.sort_values(
                by=["breakout_strength", "code"],
                ascending=[False, True]
            ).reset_index(drop=True)

        df_case.to_csv(case_file, index=False, encoding="utf-8-sig")
        all_rows.extend(df_case.to_dict(orient="records"))

        summary_rows.append({
            "scan_case": case_key,
            "scan_label": SCAN_CASES[case_key]["label"],
            "count": len(df_case),
        })

    df_all = pd.DataFrame(all_rows)
    if not df_all.empty:
        df_all = df_all.sort_values(
            by=["scan_case", "breakout_strength", "code"],
            ascending=[True, False, True]
        ).reset_index(drop=True)

    df_summary = pd.DataFrame(summary_rows)

    df_all.to_csv(os.path.join(folder, "all_breakouts.csv"), index=False, encoding="utf-8-sig")
    df_summary.to_csv(os.path.join(folder, "summary.csv"), index=False, encoding="utf-8-sig")

    return folder