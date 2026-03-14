import os
import re
import time
import calendar
from datetime import datetime, timedelta
from typing import Optional, Dict, List

import pandas as pd
import FinanceDataReader as fdr


# =========================================================
# 설정
# =========================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE_DIR, "data")
MASTER_DIR = os.path.join(DATA_DIR, "master")
RAW_DAILY_DIR = os.path.join(DATA_DIR, "raw", "daily")
DERIVED_DAILY_DIR = os.path.join(DATA_DIR, "derived", "daily")
DERIVED_WEEKLY_DIR = os.path.join(DATA_DIR, "derived", "weekly")
DERIVED_MONTHLY_DIR = os.path.join(DATA_DIR, "derived", "monthly")
LOG_DIR = os.path.join(DATA_DIR, "logs")

MASTER_FILE = os.path.join(MASTER_DIR, "kospi_tickers.csv")

START_YEARS_AGO = 10
SLEEP_SEC_BETWEEN_TICKERS = 0.12
SLEEP_SEC_BETWEEN_MASTER_CALLS = 0.02
MAX_RETRY = 3

MA_WINDOWS = [5, 10, 20, 120, 240]


# =========================================================
# 공통 유틸
# =========================================================
def ensure_dirs() -> None:
    os.makedirs(MASTER_DIR, exist_ok=True)
    os.makedirs(RAW_DAILY_DIR, exist_ok=True)
    os.makedirs(DERIVED_DAILY_DIR, exist_ok=True)
    os.makedirs(DERIVED_WEEKLY_DIR, exist_ok=True)
    os.makedirs(DERIVED_MONTHLY_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)


def today() -> datetime:
    return datetime.today()


def today_str(fmt: str = "%Y-%m-%d") -> str:
    return today().strftime(fmt)


def is_last_day_of_month(dt: Optional[datetime] = None) -> bool:
    if dt is None:
        dt = today()
    last_day = calendar.monthrange(dt.year, dt.month)[1]
    return dt.day == last_day


def safe_filename(text: str) -> str:
    text = re.sub(r'[\\/:*?"<>|]', "_", str(text))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def raw_file_path(code: str, name: str) -> str:
    return os.path.join(RAW_DAILY_DIR, f"{code}_{safe_filename(name)}.csv")


def derived_daily_file_path(code: str, name: str) -> str:
    return os.path.join(DERIVED_DAILY_DIR, f"{code}_{safe_filename(name)}.csv")


def derived_weekly_file_path(code: str, name: str) -> str:
    return os.path.join(DERIVED_WEEKLY_DIR, f"{code}_{safe_filename(name)}.csv")


def derived_monthly_file_path(code: str, name: str) -> str:
    return os.path.join(DERIVED_MONTHLY_DIR, f"{code}_{safe_filename(name)}.csv")


def initial_start_date() -> str:
    dt = today() - timedelta(days=365 * START_YEARS_AGO + 7)
    return dt.strftime("%Y-%m-%d")


def next_day(date_str: str) -> str:
    dt = pd.to_datetime(date_str) + timedelta(days=1)
    return dt.strftime("%Y-%m-%d")


def add_ma_columns(df: pd.DataFrame, close_col: str = "close") -> pd.DataFrame:
    result = df.copy()
    for w in MA_WINDOWS:
        result[f"ma{w}"] = result[close_col].rolling(window=w, min_periods=w).mean()
    return result


def clean_numeric(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    result = df.copy()
    for c in cols:
        result[c] = pd.to_numeric(result[c], errors="coerce")
    return result


# =========================================================
# 마스터 종목 목록 (FinanceDataReader)
# =========================================================
def normalize_fdr_listing(df: pd.DataFrame) -> pd.DataFrame:
    """
    FDR StockListing('KOSPI') 결과를 표준화.
    기대 컬럼: Code, Name, Market
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["code", "name", "market"])

    result = df.copy()

    col_map = {}
    for col in result.columns:
        lower = str(col).strip().lower()
        if lower == "code":
            col_map[col] = "code"
        elif lower == "name":
            col_map[col] = "name"
        elif lower == "market":
            col_map[col] = "market"

    result = result.rename(columns=col_map)

    if "code" not in result.columns:
        raise ValueError(f"StockListing 결과에 'Code' 컬럼이 없습니다. columns={list(df.columns)}")
    if "name" not in result.columns:
        raise ValueError(f"StockListing 결과에 'Name' 컬럼이 없습니다. columns={list(df.columns)}")

    if "market" not in result.columns:
        result["market"] = "KOSPI"

    result["code"] = result["code"].astype(str).str.zfill(6)
    result["name"] = result["name"].astype(str).str.strip()
    result["market"] = result["market"].astype(str).str.strip()

    result = result[["code", "name", "market"]].drop_duplicates(subset=["code"]).sort_values("code")
    return result.reset_index(drop=True)


def update_master(force: bool = False) -> pd.DataFrame:
    should_update = force or (not os.path.exists(MASTER_FILE)) or is_last_day_of_month()

    if not should_update:
        print("[MASTER] 종목 목록 갱신 생략")
        master_df = pd.read_csv(MASTER_FILE, dtype={"code": str})
        master_df["code"] = master_df["code"].astype(str).str.zfill(6)
        return master_df

    print("[MASTER] KOSPI 종목 목록 갱신 시작")

    last_error = None
    master_df = None

    for attempt in range(1, MAX_RETRY + 1):
        try:
            listing = fdr.StockListing("KOSPI")
            master_df = normalize_fdr_listing(listing)

            if not master_df.empty:
                master_df.to_csv(MASTER_FILE, index=False, encoding="utf-8-sig")
                print(f"[MASTER] 저장 완료: {MASTER_FILE} / {len(master_df)}개")
                return master_df

            print(f"[MASTER][WARN] 빈 종목 목록 반환 (attempt={attempt})")

        except Exception as e:
            last_error = e
            print(f"[MASTER][WARN] 종목 목록 조회 실패 (attempt={attempt}): {e}")

        time.sleep(1.0 * attempt)

    if os.path.exists(MASTER_FILE):
        print("[MASTER][FALLBACK] 기존 master 파일 사용")
        old_df = pd.read_csv(MASTER_FILE, dtype={"code": str})
        old_df["code"] = old_df["code"].astype(str).str.zfill(6)
        return old_df

    raise RuntimeError(f"KOSPI 종목 목록을 가져오지 못했습니다. last_error={last_error}")


# =========================================================
# 원본(raw) 일별 OHLCV (FinanceDataReader)
# =========================================================
def clean_fdr_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """
    FDR DataReader 결과를 표준 컬럼으로 변환
    기대 컬럼: Open, High, Low, Close, Volume
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    result = df.copy().reset_index()

    # 날짜 컬럼명 처리
    if "Date" in result.columns:
        result = result.rename(columns={"Date": "date"})
    else:
        first_col = result.columns[0]
        result = result.rename(columns={first_col: "date"})

    rename_map = {}
    for col in result.columns:
        lower = str(col).strip().lower()
        if lower == "open":
            rename_map[col] = "open"
        elif lower == "high":
            rename_map[col] = "high"
        elif lower == "low":
            rename_map[col] = "low"
        elif lower == "close":
            rename_map[col] = "close"
        elif lower == "volume":
            rename_map[col] = "volume"

    result = result.rename(columns=rename_map)

    required = ["date", "open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in result.columns]
    if missing:
        raise ValueError(f"필수 컬럼 누락: {missing}, columns={list(result.columns)}")

    result = result[required].copy()
    result["date"] = pd.to_datetime(result["date"]).dt.normalize()
    result = clean_numeric(result, ["open", "high", "low", "close", "volume"])
    result = result.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"], keep="last")
    result["volume"] = result["volume"].fillna(0)

    return result.reset_index(drop=True)


def fetch_ohlcv_with_retry(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    last_error = None

    for attempt in range(1, MAX_RETRY + 1):
        try:
            df = fdr.DataReader(code, start_date, end_date)
            return clean_fdr_ohlcv(df)
        except Exception as e:
            last_error = e
            print(f"[RETRY {attempt}/{MAX_RETRY}] {code} 조회 실패: {e}")
            time.sleep(1.2 * attempt)

    raise last_error


def load_raw_daily(file_path: str) -> pd.DataFrame:
    if not os.path.exists(file_path):
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    df = pd.read_csv(file_path)
    if df.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    expected = ["date", "open", "high", "low", "close", "volume"]
    for col in expected:
        if col not in df.columns:
            df[col] = pd.NA

    df = df[expected].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = clean_numeric(df, ["open", "high", "low", "close", "volume"])
    df["volume"] = df["volume"].fillna(0)
    df = df.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"], keep="last")
    return df.reset_index(drop=True)


def get_existing_last_date(file_path: str) -> Optional[str]:
    if not os.path.exists(file_path):
        return None

    try:
        df = pd.read_csv(file_path)
        if df.empty or "date" not in df.columns:
            return None
        last_dt = pd.to_datetime(df["date"]).max()
        return last_dt.strftime("%Y-%m-%d")
    except Exception:
        return None


def raw_schema_needs_refresh(file_path: str) -> bool:
    if not os.path.exists(file_path):
        return False

    try:
        df = pd.read_csv(file_path, nrows=3)
        required = {"date", "open", "high", "low", "close", "volume"}
        return not required.issubset(set(df.columns))
    except Exception:
        return True


def save_raw_daily(file_path: str, df: pd.DataFrame) -> None:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out.to_csv(file_path, index=False, encoding="utf-8-sig")


def update_one_raw_stock(code: str, name: str) -> Dict:
    file_path = raw_file_path(code, name)
    end_date = today_str("%Y-%m-%d")

    force_full_refresh = raw_schema_needs_refresh(file_path)
    if force_full_refresh:
        start_date = initial_start_date()
        mode = "REFRESH"
    else:
        last_saved = get_existing_last_date(file_path)
        if last_saved is None:
            start_date = initial_start_date()
            mode = "INIT"
        else:
            start_date = next_day(last_saved)
            mode = "INCR"

    if pd.to_datetime(start_date) > pd.to_datetime(end_date) and not force_full_refresh:
        print(f"[RAW][SKIP] {code} {name} 이미 최신")
        return {"status": "skip", "rows": 0, "updated": False}

    try:
        new_df = fetch_ohlcv_with_retry(code, start_date, end_date)

        if force_full_refresh:
            merged = new_df.copy()
        else:
            old_df = load_raw_daily(file_path)
            if new_df.empty and not old_df.empty:
                print(f"[RAW][{mode}] {code} {name} 신규 데이터 없음")
                return {"status": "empty", "rows": 0, "updated": False}

            merged = pd.concat([old_df, new_df], ignore_index=True)
            merged = merged.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)

        if merged.empty:
            print(f"[RAW][{mode}] {code} {name} 저장할 데이터 없음")
            return {"status": "empty", "rows": 0, "updated": False}

        save_raw_daily(file_path, merged)
        added_rows = len(new_df) if not force_full_refresh else len(merged)

        print(f"[RAW][{mode}] {code} {name} 저장 완료 / rows={len(merged)} / added={added_rows}")
        return {"status": mode.lower(), "rows": int(added_rows), "updated": True}

    except Exception as e:
        print(f"[RAW][FAIL] {code} {name}: {e}")
        return {"status": "fail", "rows": 0, "updated": False, "reason": str(e)}


# =========================================================
# 파생 데이터(일/주/월)
# =========================================================
def build_daily_derived(raw_df: pd.DataFrame) -> pd.DataFrame:
    if raw_df.empty:
        cols = ["date", "open", "high", "low", "close", "volume"] + [f"ma{w}" for w in MA_WINDOWS] + ["is_final"]
        return pd.DataFrame(columns=cols)

    df = raw_df.copy().sort_values("date").reset_index(drop=True)
    df = add_ma_columns(df, close_col="close")
    df["is_final"] = True
    return df


def _period_end_friday(ts: pd.Timestamp) -> pd.Timestamp:
    days_to_friday = 4 - ts.weekday()
    return (ts + pd.Timedelta(days=days_to_friday)).normalize()


def _period_end_month(ts: pd.Timestamp) -> pd.Timestamp:
    return (ts + pd.offsets.MonthEnd(0)).normalize()


def build_weekly_derived(raw_df: pd.DataFrame) -> pd.DataFrame:
    cols = ["date", "open", "high", "low", "close", "volume"] + [f"ma{w}" for w in MA_WINDOWS] + ["is_final"]
    if raw_df.empty:
        return pd.DataFrame(columns=cols)

    df = raw_df.copy().sort_values("date").reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["week_end"] = df["date"].apply(_period_end_friday)

    weekly = (
        df.groupby("week_end", as_index=False)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            last_trade_date=("date", "max"),
        )
        .rename(columns={"week_end": "date"})
        .sort_values("date")
        .reset_index(drop=True)
    )

    weekly = add_ma_columns(weekly, close_col="close")

    latest_raw_date = df["date"].max()
    latest_week_end = _period_end_friday(latest_raw_date)

    weekly["is_final"] = True
    mask_latest = weekly["date"] == latest_week_end
    weekly.loc[mask_latest, "is_final"] = latest_raw_date.weekday() == 4

    weekly = weekly.drop(columns=["last_trade_date"])
    return weekly[cols]


def build_monthly_derived(raw_df: pd.DataFrame) -> pd.DataFrame:
    cols = ["date", "open", "high", "low", "close", "volume"] + [f"ma{w}" for w in MA_WINDOWS] + ["is_final"]
    if raw_df.empty:
        return pd.DataFrame(columns=cols)

    df = raw_df.copy().sort_values("date").reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["month_end"] = df["date"].apply(_period_end_month)

    monthly = (
        df.groupby("month_end", as_index=False)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            last_trade_date=("date", "max"),
        )
        .rename(columns={"month_end": "date"})
        .sort_values("date")
        .reset_index(drop=True)
    )

    monthly = add_ma_columns(monthly, close_col="close")

    latest_raw_date = df["date"].max()
    latest_month_end = _period_end_month(latest_raw_date)

    monthly["is_final"] = True
    mask_latest = monthly["date"] == latest_month_end
    monthly.loc[mask_latest, "is_final"] = latest_raw_date == latest_month_end

    monthly = monthly.drop(columns=["last_trade_date"])
    return monthly[cols]


def save_derived_file(file_path: str, df: pd.DataFrame) -> None:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out.to_csv(file_path, index=False, encoding="utf-8-sig")


def generate_derived_for_one_stock(code: str, name: str) -> Dict:
    raw_path = raw_file_path(code, name)
    if not os.path.exists(raw_path):
        return {"status": "no_raw"}

    try:
        raw_df = load_raw_daily(raw_path)
        if raw_df.empty:
            return {"status": "empty_raw"}

        daily_df = build_daily_derived(raw_df)
        weekly_df = build_weekly_derived(raw_df)
        monthly_df = build_monthly_derived(raw_df)

        save_derived_file(derived_daily_file_path(code, name), daily_df)
        save_derived_file(derived_weekly_file_path(code, name), weekly_df)
        save_derived_file(derived_monthly_file_path(code, name), monthly_df)

        return {
            "status": "ok",
            "daily_rows": len(daily_df),
            "weekly_rows": len(weekly_df),
            "monthly_rows": len(monthly_df),
        }
    except Exception as e:
        print(f"[DERIVED][FAIL] {code} {name}: {e}")
        return {"status": "fail", "reason": str(e)}


# =========================================================
# 전체 실행
# =========================================================
def run_all(force_master_update: bool = False, derive_all: bool = True) -> None:
    """
    derive_all=True:
        raw 업데이트 여부와 상관없이 모든 종목의 derived 재계산
    derive_all=False:
        raw가 변경된 종목만 derived 재계산
    """
    ensure_dirs()

    print("======================================")
    print("KOSPI 수집 시작 (FinanceDataReader)")
    print(f"실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("======================================")

    master_df = update_master(force=force_master_update)

    raw_results = []
    derived_results = []

    total = len(master_df)
    updated_codes = set()

    for i, row in enumerate(master_df.itertuples(index=False), start=1):
        code = str(row.code).zfill(6)
        name = str(row.name).strip()

        print(f"\n[RAW {i}/{total}] {code} {name}")
        res = update_one_raw_stock(code, name)
        res["code"] = code
        res["name"] = name
        raw_results.append(res)

        if res.get("updated"):
            updated_codes.add(code)

        time.sleep(SLEEP_SEC_BETWEEN_TICKERS)

    raw_result_df = pd.DataFrame(raw_results)

    for i, row in enumerate(master_df.itertuples(index=False), start=1):
        code = str(row.code).zfill(6)
        name = str(row.name).strip()

        if (not derive_all) and (code not in updated_codes):
            derived_results.append({
                "code": code,
                "name": name,
                "status": "skip_not_updated"
            })
            continue

        print(f"\n[DERIVED {i}/{total}] {code} {name}")
        res = generate_derived_for_one_stock(code, name)
        res["code"] = code
        res["name"] = name
        derived_results.append(res)

        time.sleep(0.03)

    derived_result_df = pd.DataFrame(derived_results)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_log_file = os.path.join(LOG_DIR, f"raw_update_result_{ts}.csv")
    derived_log_file = os.path.join(LOG_DIR, f"derived_update_result_{ts}.csv")

    raw_result_df.to_csv(raw_log_file, index=False, encoding="utf-8-sig")
    derived_result_df.to_csv(derived_log_file, index=False, encoding="utf-8-sig")

    print("\n======================================")
    print("RAW 결과 요약")
    print(raw_result_df["status"].value_counts(dropna=False))
    print(f"RAW 로그: {raw_log_file}")

    print("\nDERIVED 결과 요약")
    print(derived_result_df["status"].value_counts(dropna=False))
    print(f"DERIVED 로그: {derived_log_file}")
    print("======================================")


if __name__ == "__main__":
    run_all(
        force_master_update=False,
        derive_all=True
    )