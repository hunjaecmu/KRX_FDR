from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

import pandas as pd

from config import HOLDINGS_CSV, TRACKING_OUTPUT_DIR
from data_loader import load_daily, load_weekly, load_monthly


STANDARD_COLUMNS = ["source", "code", "name", "buy_price", "quantity"]

CODE_CANDIDATES = ["code", "종목코드", "티커", "ticker"]
NAME_CANDIDATES = ["name", "종목명"]
BUY_PRICE_CANDIDATES = ["buy_price", "매수가", "매입가"]
QUANTITY_CANDIDATES = ["quantity", "보유수량", "수량", "shares"]


def _pick_column(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    lower_map = {str(col).strip().lower(): col for col in df.columns}
    for c in candidates:
        key = str(c).strip().lower()
        if key in lower_map:
            return lower_map[key]
    return None


def _normalize_target_csv(file_path: str, source: str) -> pd.DataFrame:
    if not os.path.exists(file_path):
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    raw = pd.read_csv(file_path, dtype=str)
    if raw.empty:
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    code_col = _pick_column(raw, CODE_CANDIDATES)
    if code_col is None:
        raise ValueError(f"종목코드 컬럼이 없습니다: {file_path}")

    name_col = _pick_column(raw, NAME_CANDIDATES)
    buy_col = _pick_column(raw, BUY_PRICE_CANDIDATES)
    qty_col = _pick_column(raw, QUANTITY_CANDIDATES)

    source_value = str(source).strip().upper()
    if source_value in {"H", "HOLDING", "HOLDINGS"}:
        source_value = "H"

    df = pd.DataFrame()
    df["code"] = raw[code_col].astype(str).str.strip().str.zfill(6)
    df["source"] = source_value
    df["name"] = raw[name_col].astype(str).str.strip() if name_col else ""
    df["buy_price"] = _to_number_series(raw[buy_col]) if buy_col else pd.NA
    df["quantity"] = _to_number_series(raw[qty_col]) if qty_col else pd.NA

    df = df[df["code"].str.match(r"^\d{6}$", na=False)].copy()
    df = df.drop_duplicates(subset=["source", "code"], keep="last")

    return df.reset_index(drop=True)


def _ratio_distance(price: Optional[float], ma_value: Optional[float]) -> Optional[float]:
    if price is None or ma_value is None:
        return None
    if pd.isna(price) or pd.isna(ma_value) or float(ma_value) == 0.0:
        return None
    return (float(price) / float(ma_value)) - 1.0


def _to_number_series(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.strip()
        .str.replace(",", "", regex=False)
        .str.replace("\u20a9", "", regex=False)
        .str.replace("원", "", regex=False)
    )
    cleaned = cleaned.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "N/A": pd.NA})
    return pd.to_numeric(cleaned, errors="coerce")


def _format_pct_text(value: Optional[float]) -> str:
    if value is None or pd.isna(value):
        return ""
    return f"{float(value) * 100:.1f}%"


def _latest_price_metrics(code: str) -> dict:
    try:
        df = load_daily(code)
    except Exception:
        return {
            "price_date": None,
            "current_price": None,
            "dist_ma10_ratio": None,
            "dist_ma240_ratio": None,
            "data_status": "no_data",
        }

    if df is None or df.empty:
        return {
            "price_date": None,
            "current_price": None,
            "dist_ma10_ratio": None,
            "dist_ma240_ratio": None,
            "data_status": "no_data",
        }

    recent = df.sort_values("date").iloc[-1]
    close = pd.to_numeric(recent.get("close"), errors="coerce")
    ma10 = pd.to_numeric(recent.get("ma10"), errors="coerce")
    ma240 = pd.to_numeric(recent.get("ma240"), errors="coerce")

    return {
        "price_date": pd.to_datetime(recent.get("date")).strftime("%Y-%m-%d"),
        "current_price": float(close) if pd.notna(close) else None,
        "dist_ma10_ratio": _ratio_distance(close, ma10),
        "dist_ma240_ratio": _ratio_distance(close, ma240),
        "data_status": "ok" if pd.notna(close) else "no_close",
    }


def _latest_timeframe_distance_metrics(code: str, timeframe: str) -> dict:
    loader = load_weekly if timeframe == "weekly" else load_monthly

    try:
        df = loader(code)
    except Exception:
        return {
            "close": None,
            "ma10": None,
            "ma240": None,
            "ma10_ratio": None,
            "ma240_ratio": None,
        }

    if df is None or df.empty:
        return {
            "close": None,
            "ma10": None,
            "ma240": None,
            "ma10_ratio": None,
            "ma240_ratio": None,
        }

    recent = df.sort_values("date").iloc[-1]
    close = pd.to_numeric(recent.get("close"), errors="coerce")
    ma10 = pd.to_numeric(recent.get("ma10"), errors="coerce")
    ma240 = pd.to_numeric(recent.get("ma240"), errors="coerce")

    close_val = float(close) if pd.notna(close) else None
    ma10_val = float(ma10) if pd.notna(ma10) else None
    ma240_val = float(ma240) if pd.notna(ma240) else None

    return {
        "close": close_val,
        "ma10": ma10_val,
        "ma240": ma240_val,
        "ma10_ratio": _ratio_distance(close, ma10),
        "ma240_ratio": _ratio_distance(close, ma240),
    }


def _print_negative_distance_warning(name: str, metrics: dict) -> None:
    warnings = [
        ("weekly_ma10_ratio", "주봉 10이평", metrics.get("weekly_close"), metrics.get("weekly_ma10"), metrics.get("weekly_ma10_ratio")),
        ("weekly_ma240_ratio", "주봉 240이평", metrics.get("weekly_close"), metrics.get("weekly_ma240"), metrics.get("weekly_ma240_ratio")),
        ("monthly_ma10_ratio", "월봉 10이평", metrics.get("monthly_close"), metrics.get("monthly_ma10"), metrics.get("monthly_ma10_ratio")),
        ("monthly_ma240_ratio", "월봉 240이평", metrics.get("monthly_close"), metrics.get("monthly_ma240"), metrics.get("monthly_ma240_ratio")),
    ]

    negative_rows = [item for item in warnings if item[4] is not None and float(item[4]) < 0]
    if not negative_rows:
        return

    print("Warning!")
    for _, label, close, ma_value, ratio in negative_rows:
        ratio_text = _format_pct_text(ratio)
        close_text = "" if close is None else f"{float(close):.2f}"
        ma_text = "" if ma_value is None else f"{float(ma_value):.2f}"
        print(
            f"{name} | 종가={close_text} | {label}={ma_text} | 거리={ratio_text}"
        )


def load_targets(holdings_csv: str) -> pd.DataFrame:
    holdings = _normalize_target_csv(holdings_csv, "H")
    if holdings.empty:
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    return holdings.reset_index(drop=True)


def build_snapshot(targets: pd.DataFrame, now: Optional[datetime] = None) -> pd.DataFrame:
    if now is None:
        now = datetime.now()

    run_dt = now.strftime("%Y-%m-%d %H:%M:%S")
    run_date = now.strftime("%Y-%m-%d")

    rows = []
    for row in targets.itertuples(index=False):
        metrics = _latest_price_metrics(str(row.code))
        weekly_metrics = _latest_timeframe_distance_metrics(str(row.code), timeframe="weekly")
        monthly_metrics = _latest_timeframe_distance_metrics(str(row.code), timeframe="monthly")

        distance_metrics = {
            "weekly_close": weekly_metrics.get("close"),
            "weekly_ma10": weekly_metrics.get("ma10"),
            "weekly_ma240": weekly_metrics.get("ma240"),
            "weekly_ma10_ratio": weekly_metrics.get("ma10_ratio"),
            "weekly_ma240_ratio": weekly_metrics.get("ma240_ratio"),
            "monthly_close": monthly_metrics.get("close"),
            "monthly_ma10": monthly_metrics.get("ma10"),
            "monthly_ma240": monthly_metrics.get("ma240"),
            "monthly_ma10_ratio": monthly_metrics.get("ma10_ratio"),
            "monthly_ma240_ratio": monthly_metrics.get("ma240_ratio"),
        }

        buy_price = pd.to_numeric(row.buy_price, errors="coerce")
        quantity = pd.to_numeric(row.quantity, errors="coerce")
        current_price = metrics["current_price"]


        if pd.notna(current_price) and pd.notna(buy_price):
            profit = float(current_price) - float(buy_price)
        else:
            profit = None

        if pd.notna(profit) and pd.notna(buy_price) and float(buy_price) != 0.0:
            profit_rate = float(profit) / float(buy_price)
        else:
            profit_rate = None

        if pd.notna(profit) and pd.notna(quantity):
            profit_amount = float(profit) * float(quantity)
        else:
            profit_amount = None

        if str(row.source).strip().upper() == "H":
            _print_negative_distance_warning(row.name, distance_metrics)

        rows.append({
            "snapshot_datetime": run_dt,
            "snapshot_date": run_date,
            "source": row.source,
            "code": str(row.code).zfill(6),
            "name": row.name,
            "buy_price": buy_price,
            "quantity": quantity,
            "current_price": current_price,
            "profit": profit,
            "profit_amount": profit_amount,
            "profit_rate": _format_pct_text(profit_rate),
            "weekly_ma10_ratio": _format_pct_text(distance_metrics["weekly_ma10_ratio"]),
            "weekly_ma240_ratio": _format_pct_text(distance_metrics["weekly_ma240_ratio"]),
            "monthly_ma10_ratio": _format_pct_text(distance_metrics["monthly_ma10_ratio"]),
            "monthly_ma240_ratio": _format_pct_text(distance_metrics["monthly_ma240_ratio"]),
            "price_date": metrics["price_date"],
            "data_status": metrics["data_status"],
        })

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    return out.sort_values(["source", "code"]).reset_index(drop=True)


def save_snapshot(snapshot_df: pd.DataFrame, output_dir: str, now: Optional[datetime] = None) -> dict:
    if now is None:
        now = datetime.now()

    os.makedirs(output_dir, exist_ok=True)

    ts = now.strftime("%Y%m%d_%H%M%S")
    snapshot_file = os.path.join(output_dir, f"position_snapshot_{ts}.csv")
    history_file = os.path.join(output_dir, "position_history.csv")

    snapshot_df.to_csv(snapshot_file, index=False, encoding="utf-8-sig")

    if os.path.exists(history_file):
        old_df = pd.read_csv(history_file)
        merged = pd.concat([old_df, snapshot_df], ignore_index=True)
    else:
        merged = snapshot_df.copy()

    merged.to_csv(history_file, index=False, encoding="utf-8-sig")

    return {
        "snapshot_file": snapshot_file,
        "history_file": history_file,
        "rows": int(len(snapshot_df)),
    }


def run_position_tracking(
    holdings_csv: str = HOLDINGS_CSV,
    output_dir: str = TRACKING_OUTPUT_DIR,
) -> dict:
    targets = load_targets(holdings_csv)
    if targets.empty:
        return {
            "status": "no_targets",
            "message": "입력 CSV(보유종목)가 없거나 유효한 종목코드가 없습니다.",
            "holdings_csv": holdings_csv,
        }

    snapshot_df = build_snapshot(targets)
    saved = save_snapshot(snapshot_df, output_dir=output_dir)

    return {
        "status": "ok",
        "rows": saved["rows"],
        "snapshot_file": saved["snapshot_file"],
        "history_file": saved["history_file"],
        "holdings_csv": holdings_csv,
    }


if __name__ == "__main__":
    result = run_position_tracking()
    print(result)