from __future__ import annotations

import os
from typing import Optional

import pandas as pd

from webapp import storage


def _read_last_non_empty_line(file_path: str, chunk_size: int = 1024) -> Optional[str]:
    """파일의 마지막 비어 있지 않은 줄. 끝에서부터 덩어리로 읽어 파일 수천 개도 빨리 훑는다."""
    if not os.path.isfile(file_path):
        return None

    with open(file_path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        pos = fh.tell()
        tail = b""
        while pos > 0:
            step = min(chunk_size, pos)
            pos -= step
            fh.seek(pos)
            tail = fh.read(step) + tail
            stripped = tail.rstrip(b"\r\n")
            # 앞쪽에 줄바꿈이 있으면 마지막 줄 전체를 읽은 것이다.
            if pos == 0 or b"\n" in stripped or b"\r" in stripped:
                break
        lines = [line for line in tail.splitlines() if line.strip()]

    return lines[-1].decode("utf-8", errors="ignore").strip() if lines else None


def compute_data_status(data_dir: str) -> dict:
    status = {
        "kospi_count": 0,
        "kosdaq_count": 0,
        "latest_trade_date": None,
        "latest_collection_date": None,
        "latest_collection_time": None,
        "daily_file_count": 0,
    }

    master_csv = os.path.join(data_dir, "master", "kospi_tickers.csv")
    code_market: dict = {}
    market_names = ("KOSPI", "KOSDAQ", "ETF")
    status["markets"] = {
        m: {"count": 0, "file_count": 0, "latest_trade_date": None,
            "latest_collection_date": None, "latest_collection_time": None, "_key": None}
        for m in market_names
    }
    if os.path.isfile(master_csv):
        try:
            mdf = storage.read_csv(master_csv, dtype={"code": str})
            market_series = mdf.get("market", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
            status["kospi_count"] = int((market_series == "KOSPI").sum())
            status["kosdaq_count"] = int((market_series == "KOSDAQ").sum())
            for code, mk in zip(mdf["code"].astype(str).str.zfill(6), market_series):
                grp = "KOSDAQ" if mk.startswith("KOSDAQ") else ("ETF" if mk.startswith("ETF") else "KOSPI")
                code_market[code] = grp
                status["markets"][grp]["count"] += 1
        except Exception:
            pass

    daily_dir = os.path.join(data_dir, "derived", "daily")
    if not os.path.isdir(daily_dir):
        return status

    daily_files = [f for f in os.listdir(daily_dir) if f.lower().endswith(".csv")]
    status["daily_file_count"] = len(daily_files)

    latest_trade = None
    latest_collection = None
    latest_collection_time = None
    latest_collection_key = None
    counted_codes: set = set()
    for file_name in daily_files:
        last_line = _read_last_non_empty_line(os.path.join(daily_dir, file_name))
        if not last_line:
            continue

        cols = [c.strip() for c in last_line.split(",")]
        file_code = file_name.split("_", 1)[0]
        mstat = status["markets"].get(code_market.get(file_code))
        # 종목명 변경으로 남은 옛 파일·상폐 파일은 제외하고, 마스터 종목 코드당 1회만 집계한다.
        if mstat is not None and file_code not in counted_codes:
            counted_codes.add(file_code)
            mstat["file_count"] += 1
        if cols:
            trade_date = cols[0]
            if trade_date and (latest_trade is None or trade_date > latest_trade):
                latest_trade = trade_date
            if mstat is not None and trade_date and (
                mstat["latest_trade_date"] is None or trade_date > mstat["latest_trade_date"]
            ):
                mstat["latest_trade_date"] = trade_date

        if len(cols) >= 15 and cols[13] and cols[14] and mstat is not None:
            key = f"{cols[13]} {cols[14]}"
            if mstat["_key"] is None or key > mstat["_key"]:
                mstat["_key"] = key
                mstat["latest_collection_date"] = cols[13]
                mstat["latest_collection_time"] = cols[14]

        if len(cols) >= 14:
            collection_date = cols[13]
            if collection_date and (latest_collection is None or collection_date > latest_collection):
                latest_collection = collection_date

        if len(cols) >= 15:
            collection_date = cols[13]
            collection_time = cols[14]
            if collection_date and collection_time:
                key = f"{collection_date} {collection_time}"
                if latest_collection_key is None or key > latest_collection_key:
                    latest_collection_key = key
                    latest_collection = collection_date
                    latest_collection_time = collection_time

    status["latest_trade_date"] = latest_trade
    status["latest_collection_date"] = latest_collection
    status["latest_collection_time"] = latest_collection_time
    return status
