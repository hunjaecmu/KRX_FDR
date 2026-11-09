import io
import json
import os
import re
import shutil
import socket
import time
import calendar
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime, timedelta
from typing import Optional, Dict, List

# Keep OpenBLAS from allocating a thread pool in every derived worker.
os.environ["OPENBLAS_NUM_THREADS"] = "1"

import pandas as pd
import requests
import FinanceDataReader as fdr
from config import DATA_DIR, INDEX_TICKERS

# FinanceDataReader는 timeout 없이 requests를 호출한다. 서버가 연결을 유지한 채
# 응답하지 않으면 무한 대기하고 재시도도 동작하지 않으므로 기본 timeout을 건다.
# (연결 10초, 응답 읽기 30초)
REQUEST_TIMEOUT = (10, 30)


def _install_default_request_timeout():
    original = requests.Session.request
    if getattr(original, "_krx_default_timeout", False):
        return

    def request_with_timeout(self, method, url, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = REQUEST_TIMEOUT
        return original(self, method, url, **kwargs)

    request_with_timeout._krx_default_timeout = True
    requests.Session.request = request_with_timeout


_install_default_request_timeout()

# =========================================================
# 설정
# =========================================================

MASTER_DIR = os.path.join(DATA_DIR, "master")
RAW_DAILY_DIR = os.path.join(DATA_DIR, "raw", "daily")
DERIVED_DAILY_DIR = os.path.join(DATA_DIR, "derived", "daily")
DERIVED_WEEKLY_DIR = os.path.join(DATA_DIR, "derived", "weekly")
DERIVED_MONTHLY_DIR = os.path.join(DATA_DIR, "derived", "monthly")
INDEX_DIR = os.path.join(DATA_DIR, "index")
INDEX_WEEKLY_DIR = os.path.join(INDEX_DIR, "weekly")
INDEX_MONTHLY_DIR = os.path.join(INDEX_DIR, "monthly")
LOG_DIR = os.path.join(DATA_DIR, "logs")
# 일일 시세 파일: 수집 → 이 파일 → 종목 파일 반영. 다른 PC와 공유할 때도 이 파일만 보낸다.
DAILY_CLOSE_DIR = os.path.join(DATA_DIR, "daily_close")
DAILY_CLOSE_KEEP_DAYS = 60

MASTER_FILE = os.path.join(MASTER_DIR, "kospi_tickers.csv")

START_YEARS_AGO = 25
# 요청이 몰리면 네이버 차트 서버가 응답을 멈추는 일이 있어 간격을 둔다.
SLEEP_SEC_BETWEEN_TICKERS = 0.15
SLEEP_SEC_BETWEEN_MASTER_CALLS = 0.02
MAX_RETRY = 3
DERIVED_MAX_WORKERS = 4
PROGRESS_PRINT_INTERVAL = 50

MA_WINDOWS = [5, 10, 20, 120, 180, 240]

# 장중/종가 판정 기준. 네이버 일봉은 넥스트레이드(NXT) 애프터마켓이 끝나는 20:00까지
# 값이 바뀌므로, 그 전에 받은 당일 봉은 장중으로 보고 다음 실행 때 다시 받는다.
MARKET_CLOSE_HOUR = 20
MARKET_CLOSE_MINUTE = 0


# =========================================================
# 공통 유틸
# =========================================================
def ensure_dirs() -> None:
    os.makedirs(MASTER_DIR, exist_ok=True)
    os.makedirs(RAW_DAILY_DIR, exist_ok=True)
    os.makedirs(DERIVED_DAILY_DIR, exist_ok=True)
    os.makedirs(DERIVED_WEEKLY_DIR, exist_ok=True)
    os.makedirs(DERIVED_MONTHLY_DIR, exist_ok=True)
    os.makedirs(INDEX_WEEKLY_DIR, exist_ok=True)
    os.makedirs(INDEX_MONTHLY_DIR, exist_ok=True)
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

    # Exclude zero-volume bars from MA source across all timeframes.
    if "volume" in result.columns:
        invalid_mask = pd.to_numeric(result["volume"], errors="coerce").fillna(0).eq(0)
        ma_source = pd.to_numeric(result[close_col], errors="coerce").mask(invalid_mask)
    else:
        ma_source = pd.to_numeric(result[close_col], errors="coerce")

    for w in MA_WINDOWS:
        result[f"ma{w}"] = ma_source.rolling(window=w, min_periods=w).mean()
    return result


def clean_numeric(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    result = df.copy()
    for c in cols:
        result[c] = pd.to_numeric(result[c], errors="coerce")
    return result


def normalize_zero_volume_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """
    volume=0 봉의 O/H/L/C를 마지막 거래량>0 시점의 close로 통일.
    """
    result = df.copy()
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(result.columns):
        return result

    result = clean_numeric(result, ["open", "high", "low", "close", "volume"])
    result["volume"] = result["volume"].fillna(0)

    ref_close = result["close"].where(result["volume"] > 0).ffill()
    zero_volume_mask = result["volume"].eq(0) & ref_close.notna()

    for col in ["open", "high", "low", "close"]:
        result.loc[zero_volume_mask, col] = ref_close[zero_volume_mask]

    return result

def get_run_metadata(now: Optional[datetime] = None) -> Dict[str, str]:
    if now is None:
        now = datetime.now()

    asof_datetime = now.strftime("%Y-%m-%d %H:%M:%S")
    asof_date = now.strftime("%Y-%m-%d")
    asof_time = now.strftime("%H:%M")

    is_weekday = now.weekday() < 5
    before_close = (now.hour, now.minute) < (MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE)

    if is_weekday and before_close:
        price_status = "장중"
    else:
        price_status = "종가"

    return {
        "asof_datetime": asof_datetime,
        "asof_date": asof_date,
        "asof_time": asof_time,
        "price_status": price_status,
    }


def attach_run_metadata(df: pd.DataFrame, metadata: Dict[str, str]) -> pd.DataFrame:
    result = df.copy()
    for key, value in metadata.items():
        result[key] = value
    return result


# =========================================================
# 마스터 종목 목록 (FinanceDataReader)
# =========================================================
def normalize_fdr_listing(df: pd.DataFrame) -> pd.DataFrame:
    """
    FDR StockListing 결과를 표준화.
    기대 컬럼: Code 또는 Symbol, Name, Market
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["code", "name", "market"])

    result = df.copy()

    col_map = {}
    for col in result.columns:
        lower = str(col).strip().lower()
        if lower in {"code", "symbol"}:
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


def _fetch_listing_with_retry(market_name: str) -> pd.DataFrame:
    last_error = None

    for attempt in range(1, MAX_RETRY + 1):
        try:
            listing = fdr.StockListing(market_name)
            normalized = normalize_fdr_listing(listing)

            if not normalized.empty:
                return normalized

            print(f"[MASTER][WARN] {market_name} 빈 종목 목록 반환 (attempt={attempt})")

        except Exception as e:
            last_error = e
            print(f"[MASTER][WARN] {market_name} 조회 실패 (attempt={attempt}): {e}")

        time.sleep(1.0 * attempt)

    raise RuntimeError(f"{market_name} 종목 목록 조회 실패: {last_error}")


def _needs_krx_refresh(master_file: str) -> bool:
    if not os.path.exists(master_file):
        return True

    try:
        markets = pd.read_csv(master_file, usecols=["market"])["market"]
    except Exception:
        return True

    if markets.empty:
        return True

    market_values = set(markets.astype(str).str.upper().str.strip().unique())
    return not {"KOSDAQ", "ETF/KR"}.issubset(market_values)


def update_master(force: bool = False) -> pd.DataFrame:
    should_update = (
        force
        or _needs_krx_refresh(MASTER_FILE)
        or is_last_day_of_month()
    )

    if not should_update:
        print("[MASTER] 종목 목록 갱신 생략")
        master_df = pd.read_csv(MASTER_FILE, dtype={"code": str})
        master_df["code"] = master_df["code"].astype(str).str.zfill(6)
        return master_df

    print("[MASTER] KRX(KOSPI+KOSDAQ+ETF) 종목 목록 갱신 시작")

    try:
        kospi_df = _fetch_listing_with_retry("KOSPI")
        time.sleep(SLEEP_SEC_BETWEEN_MASTER_CALLS)
        kosdaq_df = _fetch_listing_with_retry("KOSDAQ")
        time.sleep(SLEEP_SEC_BETWEEN_MASTER_CALLS)
        etf_df = _fetch_listing_with_retry("ETF/KR")
        etf_df["market"] = "ETF/KR"

        master_df = (
            pd.concat([kospi_df, kosdaq_df, etf_df], ignore_index=True)
            .sort_values("code")
            .drop_duplicates(subset=["code"], keep="first")
            .reset_index(drop=True)
        )

        if master_df.empty:
            raise RuntimeError("KOSPI+KOSDAQ+ETF 병합 결과가 비어 있습니다.")

        master_df.to_csv(MASTER_FILE, index=False, encoding="utf-8-sig")
        print(
            f"[MASTER] 저장 완료: {MASTER_FILE} / total={len(master_df)} "
            f"(KOSPI={len(kospi_df)}, KOSDAQ={len(kosdaq_df)}, ETF={len(etf_df)})"
        )
        return master_df

    except Exception as e:
        print(f"[MASTER][WARN] KRX 종목 목록 조회 실패: {e}")

    if os.path.exists(MASTER_FILE):
        print("[MASTER][FALLBACK] 기존 master 파일 사용")
        old_df = pd.read_csv(MASTER_FILE, dtype={"code": str})
        old_df["code"] = old_df["code"].astype(str).str.zfill(6)
        return old_df

    raise RuntimeError("KRX(KOSPI+KOSDAQ+ETF) 종목 목록을 가져오지 못했습니다.")


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
    result = normalize_zero_volume_ohlc(result)

    return result.reset_index(drop=True)


def fetch_ohlcv_with_retry(
    code: str,
    start_date: str,
    end_date: str,
    metadata: Dict[str, str],
) -> pd.DataFrame:
    last_error = None

    for attempt in range(1, MAX_RETRY + 1):
        try:
            df = fdr.DataReader(code, start_date, end_date)
            cleaned = clean_fdr_ohlcv(df)
            return attach_run_metadata(cleaned, metadata)
        except Exception as e:
            last_error = e
            print(f"[RETRY {attempt}/{MAX_RETRY}] {code} 조회 실패: {e}")
            time.sleep(1.2 * attempt)

    raise last_error


RAW_COLUMNS = [
    "date", "open", "high", "low", "close", "volume",
    "asof_datetime", "asof_date", "asof_time", "price_status",
]


def get_last_date_and_status(df: pd.DataFrame) -> tuple[Optional[str], Optional[str]]:
    """load_raw_daily 결과(날짜순 정렬, 중복 제거)의 마지막 날짜와 price_status."""
    if df.empty:
        return None, None

    last = df.iloc[-1]
    last_date = pd.to_datetime(last["date"]).strftime("%Y-%m-%d")
    status = last["price_status"]
    if pd.isna(status):
        return last_date, None

    status = str(status).strip()
    return last_date, status if status else None


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


def _normalize_raw(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=RAW_COLUMNS)

    for col in RAW_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    df = df[RAW_COLUMNS].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = clean_numeric(df, ["open", "high", "low", "close", "volume"])
    df["volume"] = df["volume"].fillna(0)
    df = normalize_zero_volume_ohlc(df)

    return (
        df.dropna(subset=["date"])
          .sort_values("date")
          .drop_duplicates(subset=["date"], keep="last")
          .reset_index(drop=True)
    )


def load_raw_daily(file_path: str) -> pd.DataFrame:
    if not os.path.exists(file_path):
        return pd.DataFrame(columns=RAW_COLUMNS)
    return _normalize_raw(pd.read_csv(file_path))


def load_raw_tail(file_path: str, rows: int = 10) -> pd.DataFrame:
    """파일 끝의 몇 줄만 읽는다. 저장 파일은 날짜순이므로 수집 단계에는 이것으로 충분하다."""
    if not os.path.exists(file_path):
        return pd.DataFrame(columns=RAW_COLUMNS)

    with open(file_path, "rb") as f:
        header = f.readline()
        f.seek(0, os.SEEK_END)
        size = f.tell()
        block = min(size, 16384)
        f.seek(size - block)
        data = f.read()

    # 첫 줄은 머리글이거나 중간에서 잘린 줄이다.
    lines = [line for line in data.splitlines()[1:] if line.strip()][-rows:]
    if not lines:
        return pd.DataFrame(columns=RAW_COLUMNS)
    text = header.rstrip(b"\r\n") + b"\n" + b"\n".join(lines) + b"\n"
    return _normalize_raw(pd.read_csv(io.BytesIO(text), encoding="utf-8-sig"))


def _finalize_past_rows(df: pd.DataFrame, end_date: str) -> pd.DataFrame:
    """오늘 이전 날짜의 봉은 수집 시각과 관계없이 확정된 종가다."""
    result = df.copy()
    past = pd.to_datetime(result["date"]) < pd.to_datetime(end_date)
    result.loc[past, "price_status"] = "종가"
    return result


def collect_one_stock(code: str, name: str) -> Dict:
    """
    한 종목의 새 시세를 받아 '_delta'로 돌려준다. 종목 파일은 건드리지 않는다.
    _delta의 mode: incr(기존 파일에 덧붙임) / full(전체 이력으로 교체)
    """
    file_path = raw_file_path(code, name)
    end_date = today_str("%Y-%m-%d")
    run_meta = get_run_metadata()

    base_row = None
    if raw_schema_needs_refresh(file_path):
        start_date, mode = initial_start_date(), "refresh"
    else:
        try:
            tail = load_raw_tail(file_path)
        except Exception as e:
            return {"status": "fail", "message": f"실패: {e}", "rows": 0, "updated": False, "reason": str(e)}

        last_saved, last_status = get_last_date_and_status(tail)
        if last_saved is None:
            start_date, mode = initial_start_date(), "init"
        elif last_saved == end_date and last_status == "종가":
            return {"status": "skip", "message": "이미 최신(종가)", "rows": 0, "updated": False}
        elif pd.to_datetime(last_saved) > pd.to_datetime(end_date):
            return {"status": "skip", "message": "저장 데이터 날짜가 오늘보다 미래", "rows": 0, "updated": False}
        else:
            mode = "incr"
            final = tail[tail["price_status"].astype(str).str.strip() != "장중"]
            intraday = tail[tail["price_status"].astype(str).str.strip() == "장중"]
            if not final.empty:
                base_row = final.iloc[-1]
            # 이미 확정 저장한 종가는 다시 보지 않는다. 그 다음 날부터, 장중 봉이 있으면 그 날부터 받는다.
            start_candidates = []
            if base_row is not None:
                start_candidates.append(pd.to_datetime(base_row["date"]) + timedelta(days=1))
            if not intraday.empty:
                start_candidates.append(pd.to_datetime(intraday["date"]).min())
            start_date = min(start_candidates).strftime("%Y-%m-%d")

    fetch_started = time.perf_counter()
    try:
        new_df = fetch_ohlcv_with_retry(code, start_date, end_date, metadata=run_meta)
        fetch_sec = round(time.perf_counter() - fetch_started, 3)
    except Exception as e:
        return {
            "status": "fail",
            "message": f"실패: {e}",
            "rows": 0,
            "updated": False,
            "reason": str(e),
            "fetch_sec": round(time.perf_counter() - fetch_started, 3),
        }

    new_df = new_df.dropna(how="all", subset=["open", "high", "low", "close"])
    if mode == "incr" and base_row is not None:
        # 이미 확정 저장된 봉은 다시 쓰지 않는다.
        new_df = new_df[pd.to_datetime(new_df["date"]) > pd.to_datetime(base_row["date"])]
    if new_df.empty:
        return {"status": "empty", "message": "신규 데이터 없음", "rows": 0, "updated": False, "fetch_sec": fetch_sec}

    delta = _finalize_past_rows(new_df, end_date)
    delta.insert(0, "mode", "incr" if mode == "incr" else "full")
    delta.insert(0, "name", name)
    delta.insert(0, "code", code)
    return {
        "status": mode,
        "message": f"수집 완료 / added={len(delta)}",
        "rows": int(len(delta)),
        "updated": True,
        "fetch_sec": fetch_sec,
        "_delta": delta,
    }


# =========================================================
# 일일 시세 파일 (daily_close)
#   수집한 새 시세를 먼저 이 파일 하나에 모은 뒤, 다 모이면 종목 파일에 반영한다.
#   다른 PC는 이 파일만 받아 같은 방식으로 반영한다 (scripts/share_full_data.py).
# =========================================================
DELTA_ROWS = "rows.csv"
DELTA_MANIFEST = "manifest.json"


def list_daily_close(folder: str = None) -> List[str]:
    folder = folder or DAILY_CLOSE_DIR
    if not os.path.isdir(folder):
        return []
    return sorted(
        os.path.join(folder, f) for f in os.listdir(folder)
        if re.fullmatch(r"\d{8}_\d{6}\.zip", f)
    )


def read_daily_close_manifest(path: str) -> Dict:
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read(DELTA_MANIFEST).decode("utf-8"))


def write_daily_close(delta_df: pd.DataFrame, failed: List[str], folder: str = None) -> str:
    """
    일일 시세 파일을 만든다: 새 시세(rows.csv), 종목 목록, 시장 지수, manifest.
    prev에는 바로 앞 파일 이름을 적어, 받는 쪽이 빠진 날이 없는지 확인할 수 있게 한다.
    """
    folder = folder or DAILY_CLOSE_DIR
    os.makedirs(folder, exist_ok=True)
    existing = list_daily_close(folder)
    delta_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    prev = os.path.splitext(os.path.basename(existing[-1]))[0] if existing else None
    if prev and prev >= delta_id:
        delta_id = (datetime.strptime(prev, "%Y%m%d_%H%M%S") + timedelta(seconds=1)).strftime("%Y%m%d_%H%M%S")

    out = delta_df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    modes = out.drop_duplicates("code")["mode"].value_counts().to_dict()
    manifest = {
        "id": delta_id,
        "prev": prev,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "host": socket.gethostname(),
        "trade_date": out["date"].max() if not out.empty else None,
        "stocks": int(out["code"].nunique()),
        "rows": int(len(out)),
        "incr_stocks": int(modes.get("incr", 0)),
        "full_stocks": int(modes.get("full", 0)),
        "failed": sorted(failed),
    }

    target = os.path.join(folder, f"{delta_id}.zip")
    temp = target + ".tmp"
    with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(DELTA_ROWS, out.to_csv(index=False))
        if os.path.exists(MASTER_FILE):
            z.write(MASTER_FILE, "master/" + os.path.basename(MASTER_FILE))
        if os.path.isdir(INDEX_DIR):
            for root, _, files in os.walk(INDEX_DIR):
                for f in sorted(files):
                    path = os.path.join(root, f)
                    z.write(path, "index/" + os.path.relpath(path, INDEX_DIR).replace(os.sep, "/"))
        z.writestr(DELTA_MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
    os.replace(temp, target)
    return target


def prune_daily_close(folder: str = None, keep_days: int = None) -> None:
    keep_days = DAILY_CLOSE_KEEP_DAYS if keep_days is None else keep_days
    cutoff = (today() - timedelta(days=keep_days)).strftime("%Y%m%d")
    for path in list_daily_close(folder):
        if os.path.basename(path)[:8] < cutoff:
            os.remove(path)


def read_daily_close_rows(path: str) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        with z.open(DELTA_ROWS) as f:
            return pd.read_csv(f, dtype={"code": str})


def apply_daily_rows(rows: pd.DataFrame) -> Dict[str, Dict]:
    """일일 시세 파일의 행을 종목 파일에 반영한다. 같은 날짜는 새 값으로 바꾼다."""
    results: Dict[str, Dict] = {}
    if rows.empty:
        return results
    rows = rows.copy()
    rows["code"] = rows["code"].astype(str).str.zfill(6)
    for (code, name), group in rows.groupby(["code", "name"], sort=False):
        path = raw_file_path(code, name)
        mode = group["mode"].iloc[0]
        new_df = _normalize_raw(group.drop(columns=["code", "name", "mode"]))
        try:
            if mode == "full":
                merged = new_df
            else:
                if not os.path.exists(path):
                    results[code] = {"status": "missing_base", "name": name}
                    print(f"[APPLY][WARN] {code} {name}: 기존 파일이 없어 반영하지 못했습니다.")
                    continue
                merged = (
                    pd.concat([load_raw_daily(path), new_df], ignore_index=True)
                      .sort_values("date")
                      .drop_duplicates(subset=["date"], keep="last")
                      .reset_index(drop=True)
                )
            save_raw_daily(path, merged)
            results[code] = {"status": "ok", "name": name, "rows": len(merged)}
        except Exception as e:
            print(f"[APPLY][FAIL] {code} {name}: {e}")
            results[code] = {"status": "fail", "name": name, "reason": str(e)}
    return results


def install_daily_close_extras(path: str) -> None:
    """일일 시세 파일에 담긴 종목 목록과 시장 지수 파일을 설치한다 (다른 PC용)."""
    ensure_dirs()
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            name = info.filename
            if name.startswith("/") or ".." in name.split("/") or ":" in name:
                raise ValueError(f"잘못된 경로가 묶음에 있습니다: {name}")
            if name.startswith("master/"):
                dest = os.path.join(MASTER_DIR, name[len("master/"):])
            elif name.startswith("index/"):
                dest = os.path.join(INDEX_DIR, *name[len("index/"):].split("/"))
            else:
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(info) as src, open(dest + ".tmp", "wb") as dst:
                shutil.copyfileobj(src, dst)
            os.replace(dest + ".tmp", dest)


# =========================================================
# 파생 데이터(일/주/월)
# =========================================================

def build_daily_derived(raw_df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "date", "open", "high", "low", "close", "volume",
        "ma5", "ma10", "ma20", "ma120", "ma180", "ma240",
        "is_final",
        "asof_datetime", "asof_date", "asof_time", "price_status",
    ]

    if raw_df.empty:
        return pd.DataFrame(columns=cols)

    df = raw_df.copy().sort_values("date").reset_index(drop=True)
    df = add_ma_columns(df, close_col="close")
    df["is_final"] = True
    return df[cols]

def _period_end_friday(ts: pd.Timestamp) -> pd.Timestamp:
    days_to_friday = 4 - ts.weekday()
    return (ts + pd.Timedelta(days=days_to_friday)).normalize()


def _period_end_month(ts: pd.Timestamp) -> pd.Timestamp:
    return (ts + pd.offsets.MonthEnd(0)).normalize()


def build_weekly_derived(raw_df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "date", "open", "high", "low", "close", "volume",
        "ma5", "ma10", "ma20", "ma120", "ma180", "ma240",
        "is_final",
        "asof_datetime", "asof_date", "asof_time", "price_status",
    ]
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
            asof_datetime=("asof_datetime", "last"),
            asof_date=("asof_date", "last"),
            asof_time=("asof_time", "last"),
            price_status=("price_status", "last"),
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
    cols = [
        "date", "open", "high", "low", "close", "volume",
        "ma5", "ma10", "ma20", "ma120", "ma180", "ma240",
        "is_final",
        "asof_datetime", "asof_date", "asof_time", "price_status",
    ]
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
            asof_datetime=("asof_datetime", "last"),
            asof_date=("asof_date", "last"),
            asof_time=("asof_time", "last"),
            price_status=("price_status", "last"),
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
def build_index_summary(code: str, name: str, raw_df: pd.DataFrame) -> Dict:
    """최신 거래일의 종가와 전일 대비 등락률."""
    ordered = raw_df.sort_values("date")
    last = ordered.iloc[-1]
    close = float(last["close"])
    prev_close = float(ordered.iloc[-2]["close"]) if len(ordered) >= 2 else None
    last_date = pd.to_datetime(last["date"]).strftime("%Y-%m-%d")
    # 수집 시각이 장중이어도 지난 거래일의 값은 이미 확정된 종가다.
    price_status = str(last.get("price_status", "")) if last_date == today_str("%Y-%m-%d") else "종가"
    return {
        "code": code,
        "name": name,
        "date": last_date,
        "close": close,
        "change_pct": (close / prev_close - 1) * 100 if prev_close else None,
        "price_status": price_status,
    }


def update_indices() -> None:
    """시장 지수의 주봉, 월봉, 당일 요약을 새로 만든다. 실패하면 기존 파일을 유지한다."""
    ensure_dirs()
    run_meta = get_run_metadata()
    for code, name in INDEX_TICKERS:
        try:
            raw_df = fetch_ohlcv_with_retry(code, initial_start_date(), today_str("%Y-%m-%d"), metadata=run_meta)
            if raw_df.empty:
                raise ValueError("조회 결과가 없습니다.")
            weekly_df = build_weekly_derived(raw_df)
            monthly_df = build_monthly_derived(raw_df)
            summary = build_index_summary(code, name, raw_df)
            save_derived_file(os.path.join(INDEX_WEEKLY_DIR, f"{code}_{name}.csv"), weekly_df)
            save_derived_file(os.path.join(INDEX_MONTHLY_DIR, f"{code}_{name}.csv"), monthly_df)
            with open(os.path.join(INDEX_DIR, f"{code}_summary.json"), "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False)
            print(f"[INDEX] {name} 저장 완료")
        except Exception as e:
            print(f"[INDEX][WARN] {name} 갱신 실패: {e}")


def market_group(market: str) -> str:
    m = str(market).upper().strip()
    if m.startswith("KOSDAQ"):
        return "KOSDAQ"
    if m.startswith("ETF"):
        return "ETF"
    return "KOSPI"


def generate_derived_all(
    tasks: List[tuple[str, str]],
    total: int,
    max_workers: int = DERIVED_MAX_WORKERS,
) -> Dict[str, Dict]:
    results: Dict[str, Dict] = {}

    def record(code: str, res: Dict) -> None:
        results[code] = res
        done = len(results)
        if done % PROGRESS_PRINT_INTERVAL == 0 or done == len(tasks):
            print(f"[DERIVED {done}/{total}] 진행중", flush=True)

    if max_workers > 1 and len(tasks) > 1:
        try:
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                future_map = {
                    executor.submit(generate_derived_for_one_stock, code, name): code
                    for code, name in tasks
                }
                for future in as_completed(future_map):
                    code = future_map[future]
                    try:
                        record(code, future.result())
                    except BrokenProcessPool:
                        raise
                    except Exception as e:
                        print(f"[DERIVED][FAIL] {code}: {e}")
                        record(code, {"status": "fail", "reason": str(e)})
        except BrokenProcessPool as e:
            print(f"[DERIVED][WARN] process pool 종료, 남은 종목을 순차 처리합니다: {e}")

    # 순차 실행이거나 process pool이 중단되어 남은 종목
    for code, name in tasks:
        if code not in results:
            record(code, generate_derived_for_one_stock(code, name))

    return results


def append_timing_log(row: Dict) -> None:
    timing_file = os.path.join(LOG_DIR, "update_timing.csv")
    pd.DataFrame([row]).to_csv(
        timing_file,
        mode="a",
        header=not os.path.exists(timing_file),
        index=False,
        encoding="utf-8-sig",
    )


def run_all(
    force_master_update: bool = False,
    derive_all: bool = True,
    markets: Optional[List[str]] = None,
) -> None:
    """
    derive_all=True:
        raw 업데이트 여부와 상관없이 모든 종목의 derived 재계산
    derive_all=False:
        raw가 변경된 종목만 derived 재계산
    markets: "KOSPI", "KOSDAQ", "ETF" 중 업데이트할 시장 (None이면 전체)
    """
    ensure_dirs()

    selected = [m.upper() for m in markets] if markets else ["KOSPI", "KOSDAQ", "ETF"]

    print("======================================")
    print(f"KRX({'+'.join(selected)}) 수집 시작 (FinanceDataReader)")
    print(f"실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("======================================")

    run_started = time.perf_counter()
    master_df = update_master(force=force_master_update)
    master_df = master_df[master_df["market"].map(market_group).isin(selected)].reset_index(drop=True)
    master_sec = time.perf_counter() - run_started

    raw_results: Dict[str, Dict] = {}
    derived_results = []
    total = len(master_df)
    tickers = [(str(r.code).zfill(6), str(r.name).strip()) for r in master_df.itertuples(index=False)]

    # 1) 수집: 새 시세를 메모리에 모은다. 종목 파일은 아직 건드리지 않는다.
    raw_started = time.perf_counter()
    deltas: List[pd.DataFrame] = []

    def collect(code: str, name: str) -> Dict:
        res = collect_one_stock(code, name)
        delta = res.pop("_delta", None)
        if delta is not None:
            deltas.append(delta)
        res["code"] = code
        res["name"] = name
        raw_results[code] = res
        if "fetch_sec" in res:  # 서버에 요청한 종목만 간격을 둔다.
            time.sleep(SLEEP_SEC_BETWEEN_TICKERS)
        return res

    for i, (code, name) in enumerate(tickers, start=1):
        collect(code, name)
        if i % 50 == 0 or i == total:
            print(f"[RAW {i}/{total}] 진행중")

    failed = [(c, r["name"]) for c, r in raw_results.items() if r["status"] == "fail"]
    if failed:
        print(f"[RAW] 실패 {len(failed)}종목 다시 시도")
        time.sleep(5)
        for code, name in failed:
            collect(code, name)
    failed_codes = [c for c, r in raw_results.items() if r["status"] == "fail"]

    # 2) 일일 시세 파일: 시장 지수까지 받은 뒤 한 파일로 저장한다.
    if set(selected) == {"KOSPI", "KOSDAQ", "ETF"}:
        update_indices()
    delta_df = pd.concat(deltas, ignore_index=True) if deltas else pd.DataFrame()
    if not delta_df.empty:
        delta_path = write_daily_close(delta_df, failed_codes)
        prune_daily_close()
        print(f"[DAILY] 일일 시세 파일 저장: {delta_path} ({len(delta_df):,}행, {delta_df['code'].nunique():,}종목)")
    else:
        print("[DAILY] 새 시세가 없어 일일 시세 파일을 만들지 않습니다.")
    if failed_codes:
        print(f"[DAILY][WARN] 받지 못한 종목 {len(failed_codes)}개는 반영하지 않습니다: {', '.join(failed_codes[:20])}")

    # 3) 반영: 일일 시세 파일의 내용을 종목 파일에 반영한다.
    applied = apply_daily_rows(delta_df)
    for code, res in applied.items():
        if res["status"] != "ok":
            raw_results[code]["status"] = "fail"
            raw_results[code]["message"] = f"반영 실패: {res.get('reason', res['status'])}"
    updated_codes = {c for c, res in applied.items() if res["status"] == "ok"}
    raw_result_df = pd.DataFrame([raw_results[c] for c, _ in tickers])
    raw_sec = time.perf_counter() - raw_started

    derived_started = time.perf_counter()
    derive_tasks = [(c, n) for c, n in tickers if derive_all or c in updated_codes]
    derived_by_code = generate_derived_all(derive_tasks, total=len(derive_tasks))

    for code, name in tickers:
        res = derived_by_code.get(code, {"status": "skip_not_updated"})
        res["code"] = code
        res["name"] = name
        derived_results.append(res)

    derived_result_df = pd.DataFrame(derived_results)
    derived_sec = time.perf_counter() - derived_started

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_log_file = os.path.join(LOG_DIR, f"raw_update_result_{ts}.csv")
    derived_log_file = os.path.join(LOG_DIR, f"derived_update_result_{ts}.csv")

    raw_result_df.to_csv(raw_log_file, index=False, encoding="utf-8-sig")
    derived_result_df.to_csv(derived_log_file, index=False, encoding="utf-8-sig")

    fetch_sec = raw_result_df["fetch_sec"].sum() if "fetch_sec" in raw_result_df.columns else 0.0
    append_timing_log({
        "started_at": datetime.fromtimestamp(time.time() - (time.perf_counter() - run_started)).strftime("%Y-%m-%d %H:%M:%S"),
        "stocks": total,
        "master_sec": round(master_sec, 1),
        "raw_sec": round(raw_sec, 1),
        "fetch_sec": round(float(fetch_sec), 1),
        "derived_sec": round(derived_sec, 1),
        "derived_workers": DERIVED_MAX_WORKERS,
    })

    print("\n======================================")
    print("RAW 결과 요약")
    print(raw_result_df["status"].value_counts(dropna=False))
    print(f"RAW 로그: {raw_log_file}")

    print("\nDERIVED 결과 요약")
    print(derived_result_df["status"].value_counts(dropna=False))
    print(f"DERIVED 로그: {derived_log_file}")

    print(
        f"\n소요 시간: 전체 {time.perf_counter() - run_started:.0f}초 "
        f"(RAW {raw_sec:.0f}초, 조회 합계 {fetch_sec:.0f}초, DERIVED {derived_sec:.0f}초)"
    )
    print("======================================")


if __name__ == "__main__":
    import sys

    run_all(
        force_master_update=False,
        derive_all=True,
        markets=sys.argv[1:] or None,
    )

    from webapp import auto_publish

    if auto_publish.is_full_update(sys.argv[1:]):
        auto_publish.publish_after("전체 데이터 업데이트")
