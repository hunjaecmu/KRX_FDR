# market_scanner.py

from __future__ import annotations

import os
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
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
    "monthly_ma240_breakout": {
        "timeframe": "monthly",
        "ma_col": "ma240",
        "label": "월봉 240이평 돌파",
    },
}

DEFAULT_MAX_WORKERS = max(1, (os.cpu_count() or 2) - 1)


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
        "breakout_pct": strength * 100 if strength is not None else None,
        "is_final": curr_row["is_final"] if "is_final" in curr_row.index else None,
    }


def _scan_one_stock(row_data: tuple[str, str]) -> list[dict]:
    """
    종목 1개에 대해 모든 케이스를 검사해서 결과 row list 반환
    멀티프로세싱용 top-level 함수
    """
    code, name = row_data
    out: list[dict] = []

    for case_key, meta in SCAN_CASES.items():
        try:
            df = _load_by_timeframe(code, meta["timeframe"])
            info = detect_breakout_up(df, meta["ma_col"])
            if info is None:
                continue

            out.append({
                "scan_case": case_key,
                "scan_label": meta["label"],
                "timeframe": meta["timeframe"],
                "ma_col": meta["ma_col"],
                "code": code,
                "name": name,
                "date": pd.to_datetime(info["date"]).strftime("%Y-%m-%d"),
                "close": info["close"],
                "ma_value": info["ma_value"],
                "prev_close": info["prev_close"],
                "prev_ma_value": info["prev_ma_value"],
                "breakout_strength": info["breakout_strength"],
                "breakout_pct": info["breakout_pct"],
                "is_final": info["is_final"],
            })
        except Exception:
            continue

    return out


def scan_all_breakouts_parallel(max_workers: Optional[int] = None) -> dict[str, list[dict]]:
    """
    멀티프로세싱 버전
    """
    master = load_master()

    if max_workers is None:
        max_workers = DEFAULT_MAX_WORKERS

    tasks = []
    for row in master.itertuples(index=False):
        code = str(row.code).zfill(6)
        name = str(row.name)
        tasks.append((code, name))

    results: dict[str, list[dict]] = {case_key: [] for case_key in SCAN_CASES.keys()}

    print(f"[SCAN] 멀티프로세싱 시작 | 종목 수={len(tasks)} | workers={max_workers}")

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_scan_one_stock, task): task for task in tasks}

        done_count = 0
        total_count = len(future_map)

        for future in as_completed(future_map):
            code, name = future_map[future]
            done_count += 1

            try:
                rows = future.result()
                for row in rows:
                    results[row["scan_case"]].append(row)
            except Exception as e:
                print(f"[SCAN][WARN] worker 실패: {code} {name} / {e}")

            if done_count % 100 == 0 or done_count == total_count:
                print(f"[SCAN] 진행률: {done_count}/{total_count}")

    # 돌파강도 낮은 것부터 높은 것 순서로 정렬
    for case_key in results.keys():
        results[case_key].sort(
            key=lambda x: (
                999999 if x["breakout_strength"] is None else x["breakout_strength"],
                x["code"],
            )
        )

    return results


def scan_all_breakouts(max_workers: Optional[int] = None) -> dict[str, list[dict]]:
    """
    기존 인터페이스 유지용.
    내부적으로 멀티프로세싱 실행.
    """
    return scan_all_breakouts_parallel(max_workers=max_workers)


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
                - monthly_ma240_breakout.csv
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
            # 돌파강도 낮은 순 정렬
            df_case = df_case.sort_values(
                by=["breakout_strength", "code"],
                ascending=[True, True]
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
        # 전체 파일도 돌파강도 낮은 순 정렬
        df_all = df_all.sort_values(
            by=["scan_case", "breakout_strength", "code"],
            ascending=[True, True, True]
        ).reset_index(drop=True)

    df_summary = pd.DataFrame(summary_rows)

    df_all.to_csv(os.path.join(folder, "all_breakouts.csv"), index=False, encoding="utf-8-sig")
    df_summary.to_csv(os.path.join(folder, "summary.csv"), index=False, encoding="utf-8-sig")

    return folder