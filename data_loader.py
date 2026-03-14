# data_loader.py

import os
import pandas as pd
from config import DATA_DIR

MASTER_FILE = os.path.join(DATA_DIR, "master", "kospi_tickers.csv")

RAW_DAILY_DIR = os.path.join(DATA_DIR, "raw", "daily")
DERIVED_DAILY_DIR = os.path.join(DATA_DIR, "derived", "daily")
DERIVED_WEEKLY_DIR = os.path.join(DATA_DIR, "derived", "weekly")
DERIVED_MONTHLY_DIR = os.path.join(DATA_DIR, "derived", "monthly")


def get_weekly_file_path(code: str):
    return _find_file(DERIVED_WEEKLY_DIR, code)


def get_monthly_file_path(code: str):
    return _find_file(DERIVED_MONTHLY_DIR, code)


def load_master() -> pd.DataFrame:
    df = pd.read_csv(MASTER_FILE, dtype={"code": str})
    df["code"] = df["code"].astype(str).str.zfill(6)
    return df.sort_values("code").reset_index(drop=True)


def get_name_map() -> dict:
    df = load_master()
    return dict(zip(df["code"], df["name"]))


def get_ticker_name(code: str):
    code = str(code).zfill(6)
    df = load_master()
    row = df[df["code"] == code]

    if row.empty:
        return None

    return row.iloc[0]["name"]


def _find_file(folder: str, code: str):
    code = str(code).zfill(6)

    if not os.path.exists(folder):
        return None

    for f in os.listdir(folder):
        if f.startswith(code + "_") and f.endswith(".csv"):
            return os.path.join(folder, f)

    return None


def _load_csv_with_date(file_path: str) -> pd.DataFrame:
    if file_path is None or not os.path.exists(file_path):
        raise FileNotFoundError(file_path)

    df = pd.read_csv(file_path)

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])

    numeric_cols = [
        "open", "high", "low", "close", "volume",
        "ma5", "ma10", "ma20", "ma120", "ma240"
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "is_final" in df.columns and df["is_final"].dtype == object:
        df["is_final"] = df["is_final"].astype(str).str.lower().map({
            "true": True,
            "false": False
        })

    return df.sort_values("date").reset_index(drop=True)


def load_raw_daily(code: str) -> pd.DataFrame:
    return _load_csv_with_date(_find_file(RAW_DAILY_DIR, code))


def load_daily(code: str) -> pd.DataFrame:
    return _load_csv_with_date(_find_file(DERIVED_DAILY_DIR, code))


def load_weekly(code: str) -> pd.DataFrame:
    return _load_csv_with_date(_find_file(DERIVED_WEEKLY_DIR, code))


def load_monthly(code: str) -> pd.DataFrame:
    return _load_csv_with_date(_find_file(DERIVED_MONTHLY_DIR, code))