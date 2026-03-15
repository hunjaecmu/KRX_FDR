# replay_latest_scan.py

from __future__ import annotations

import os
import re
from typing import Dict, List

import pandas as pd

from config import OUTPUT_DIR
from chart_viewer import create_overview_image, auto_slide_breakout_charts


SCAN_CASES = [
    "weekly_ma10_breakout",
    "weekly_ma240_breakout",
    "monthly_ma10_breakout",
    "monthly_ma240_breakout",
]


def _find_latest_scan_result_folder(output_dir: str) -> str:
    if not os.path.exists(output_dir):
        raise FileNotFoundError(f"OUTPUT_DIR가 존재하지 않습니다: {output_dir}")

    candidates = []
    pattern = re.compile(r"^scan_result_(\d{8}_\d{6})$")

    for name in os.listdir(output_dir):
        full_path = os.path.join(output_dir, name)
        if not os.path.isdir(full_path):
            continue

        m = pattern.match(name)
        if m:
            candidates.append((m.group(1), full_path))

    if not candidates:
        raise FileNotFoundError(f"scan_result 폴더를 찾지 못했습니다: {output_dir}")

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _load_case_csv(case_file: str) -> List[dict]:
    if not os.path.exists(case_file):
        return []

    df = pd.read_csv(case_file)
    if df.empty:
        return []

    # 숫자형 컬럼 보정
    numeric_cols = [
        "close",
        "ma_value",
        "prev_close",
        "prev_ma_value",
        "breakout_strength",
        "breakout_pct",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # bool 보정
    if "is_final" in df.columns and df["is_final"].dtype == object:
        df["is_final"] = df["is_final"].astype(str).str.lower().map({
            "true": True,
            "false": False,
        })

    return df.to_dict(orient="records")


def load_results_from_scan_folder(scan_folder: str) -> Dict[str, List[dict]]:
    results: Dict[str, List[dict]] = {}

    for case_key in SCAN_CASES:
        case_file = os.path.join(scan_folder, f"{case_key}.csv")
        results[case_key] = _load_case_csv(case_file)

    return results


def print_loaded_summary(results: Dict[str, List[dict]], scan_folder: str) -> None:
    print("=" * 70)
    print(f"최신 스캔 결과 폴더: {scan_folder}")
    print("=" * 70)

    total = 0
    for case_key in SCAN_CASES:
        count = len(results.get(case_key, []))
        total += count
        print(f"{case_key:>24} : {count:>4}개")

    print("-" * 70)
    print(f"{'total':>24} : {total:>4}개")
    print("=" * 70)


def main():
    scan_folder = _find_latest_scan_result_folder(OUTPUT_DIR)
    results = load_results_from_scan_folder(scan_folder)

    print_loaded_summary(results, scan_folder)

    # 오버뷰 먼저 표시
    overview_path = create_overview_image(
        results,
        save_root=scan_folder,
        min_pct=0.5,
        max_pct=5.0,
        show_first_page=True,
        pause_sec=3.0,
    )
    print(f"오버뷰 이미지: {overview_path}")

    # 각 영역별 최대 5개만 자동 슬라이드
    auto_slide_breakout_charts(
        results,
        save_root=scan_folder,
        min_pct=0.5,
        max_pct=5.0,
        pause_sec=2.0,
        max_per_case=5,
    )

if __name__ == "__main__":
    main()