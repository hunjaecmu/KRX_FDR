from __future__ import annotations

import os
import re
import shutil
import tempfile
from datetime import date, datetime
from typing import Optional

import pandas as pd

from config import RECORD_FILE_OPTIONS, TRACKING_INPUT_DIR

READ_ENCODINGS = ("utf-8-sig", "cp949")
WRITE_ENCODING = "utf-8-sig"
BACKUP_DIRNAME = "_backup"
BACKUP_KEEP_COUNT = 30

HOLDINGS_CODE_CANDIDATES = ["code", "종목코드", "티커", "ticker"]
HOLDINGS_NAME_CANDIDATES = ["name", "종목명"]
HOLDINGS_BUY_PRICE_CANDIDATES = ["buy_price", "매수가", "매입가"]
HOLDINGS_QUANTITY_CANDIDATES = ["quantity", "보유수량", "수량", "shares"]
HOLDINGS_MEMO_CANDIDATES = ["memo", "메모", "note", "비고"]


class CsvReadError(Exception):
    """기존 CSV를 읽지 못함. 덮어쓰기 전에 저장을 중단하기 위해 사용한다."""


def read_csv(file_path: str, **kwargs) -> pd.DataFrame:
    for encoding in READ_ENCODINGS:
        try:
            return pd.read_csv(file_path, encoding=encoding, **kwargs)
        except UnicodeDecodeError:
            continue
        except pd.errors.EmptyDataError:
            return pd.DataFrame()
        except (OSError, pd.errors.ParserError) as e:
            raise CsvReadError(f"{file_path} 읽기 실패: {e}") from e

    raise CsvReadError(f"{file_path} 읽기 실패: 지원하지 않는 인코딩입니다.")


def _backup_file(file_path: str) -> None:
    folder, filename = os.path.split(file_path)
    stem, ext = os.path.splitext(filename)
    backup_dir = os.path.join(folder, BACKUP_DIRNAME)
    os.makedirs(backup_dir, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    shutil.copy2(file_path, os.path.join(backup_dir, f"{stem}_{stamp}{ext}"))

    pattern = re.compile(re.escape(stem) + r"_\d{8}_\d{6}_\d{6}" + re.escape(ext))
    backups = sorted(f for f in os.listdir(backup_dir) if pattern.fullmatch(f))
    for old in backups[:-BACKUP_KEEP_COUNT]:
        os.remove(os.path.join(backup_dir, old))


def write_csv(file_path: str, df: pd.DataFrame) -> None:
    folder = os.path.dirname(file_path)
    os.makedirs(folder, exist_ok=True)

    if os.path.isfile(file_path):
        _backup_file(file_path)

    # 저장 도중 실패해도 원본이 남도록 임시 파일에 쓴 뒤 교체
    fd, temp_path = tempfile.mkstemp(dir=folder, prefix=".tmp_", suffix=".csv")
    os.close(fd)
    try:
        df.to_csv(temp_path, index=False, encoding=WRITE_ENCODING)
        os.replace(temp_path, file_path)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


def append_row(file_path: str, row: dict) -> None:
    row_df = pd.DataFrame([row])
    if os.path.isfile(file_path):
        old_df = read_csv(file_path, dtype=str)
        out_df = pd.concat([old_df, row_df], ignore_index=True)
    else:
        out_df = row_df

    write_csv(file_path, out_df)


def record_display_options() -> list[str]:
    return [f"{label}: {fname.replace('.csv', '')}" for label, fname in RECORD_FILE_OPTIONS]


def record_label_to_filename(display_label: str) -> str:
    left_label = str(display_label).split(":", 1)[0].strip()
    return dict(RECORD_FILE_OPTIONS).get(left_label, "MA10_W_Break.csv")


def interest_watch_month_token(ref_date: Optional[date] = None) -> str:
    base = ref_date if ref_date is not None else date.today()
    return f"{base.year:04d}{base.month:02d}"


def interest_watch_monthly_filename(month_token: str) -> str:
    return f"watch_{str(month_token).strip()}.csv"


def interest_watch_monthly_path(month_token: Optional[str] = None) -> str:
    token = str(month_token).strip() if month_token else interest_watch_month_token()
    return os.path.join(TRACKING_INPUT_DIR, interest_watch_monthly_filename(token))


def parse_interest_watch_month_from_filename(filename: str) -> Optional[str]:
    name = str(filename).strip()
    m1 = re.match(r"^watch_(\d{6})\.csv$", name)
    if m1:
        return m1.group(1)
    m2 = re.match(r"^(\d{6})\.csv$", name)
    if m2:
        return m2.group(1)
    return None


def interest_watch_file_options(tracking_dir: str) -> list[tuple[str, str]]:
    options: list[tuple[str, str]] = []
    current_month = interest_watch_month_token()
    current_path = interest_watch_monthly_path(current_month)
    options.append((f"{current_month} (현재월)", current_path))

    if not os.path.isdir(tracking_dir):
        return options

    month_map: dict[str, str] = {}
    legacy_path = None
    for fname in os.listdir(tracking_dir):
        full_path = os.path.join(tracking_dir, fname)
        if not os.path.isfile(full_path):
            continue
        if str(fname).lower() == "watch.csv":
            legacy_path = full_path
            continue

        month_token = parse_interest_watch_month_from_filename(str(fname))
        if month_token:
            month_map[month_token] = full_path

    for month_token in sorted(month_map.keys(), reverse=True):
        display = f"{month_token}"
        if month_token == current_month:
            display = f"{month_token} (현재월)"
        pair = (display, month_map[month_token])
        if pair not in options:
            options.append(pair)

    if legacy_path:
        options.append(("legacy watch.csv", legacy_path))

    return options


def pick_column(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    lower_map = {str(col).strip().lower(): col for col in df.columns}
    for c in candidates:
        key = str(c).strip().lower()
        if key in lower_map:
            return lower_map[key]
    return None


def load_holdings_source_df(holdings_path: str) -> pd.DataFrame:
    if os.path.isfile(holdings_path):
        return read_csv(holdings_path, dtype=str).fillna("")
    return pd.DataFrame(columns=["종목코드", "종목명", "매수가", "보유수량", "메모"])


def add_holding_row(
    holdings_path: str,
    code: str,
    name: str,
    buy_price_text: str,
    quantity_text: str,
    memo_text: str,
) -> None:
    hdf = load_holdings_source_df(holdings_path)

    code_col = pick_column(hdf, HOLDINGS_CODE_CANDIDATES) or "종목코드"
    name_col = pick_column(hdf, HOLDINGS_NAME_CANDIDATES) or "종목명"
    buy_col = pick_column(hdf, HOLDINGS_BUY_PRICE_CANDIDATES) or "매수가"
    qty_col = pick_column(hdf, HOLDINGS_QUANTITY_CANDIDATES) or "보유수량"
    memo_col = pick_column(hdf, HOLDINGS_MEMO_CANDIDATES) or "메모"

    for col in [code_col, name_col, buy_col, qty_col, memo_col]:
        if col not in hdf.columns:
            hdf[col] = ""

    new_row = {col: "" for col in hdf.columns}
    new_row[code_col] = str(code).strip().zfill(6)
    new_row[name_col] = str(name).strip()
    new_row[buy_col] = str(buy_price_text).strip()
    new_row[qty_col] = str(quantity_text).strip()
    new_row[memo_col] = str(memo_text)

    out_df = pd.concat([hdf, pd.DataFrame([new_row])], ignore_index=True)
    write_csv(holdings_path, out_df)
