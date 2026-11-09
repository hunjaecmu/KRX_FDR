# scripts/import_icloud_data.py
"""Mac에서 만든 iCloud Drive의 데이터 묶음(krx_full_data.zip)을 PC 데이터에 합친다.

Mac 데이터가 기준이다. 묶음에 있는 날짜는 Mac 값으로 바꾸고, PC에만 있는 더 오래된 이력은 남긴다.
바뀐 종목만 주봉·월봉 등 파생 데이터를 다시 만든다.
"""

import argparse
import glob
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import pandas as pd

import config
from data_store import (
    INDEX_DIR,
    LOG_DIR,
    MASTER_FILE,
    RAW_DAILY_DIR,
    ensure_dirs,
    generate_derived_all,
    load_raw_daily,
    raw_file_path,
    safe_filename,
    save_raw_daily,
)
from webapp import auto_publish

DEFAULT_ZIP = os.getenv("KRX_ICLOUD_ZIP", r"D:\iCloud Drive\iCloudDrive\KRX_FDR\krx_full_data.zip")
STATE_FILE = os.path.join(LOG_DIR, "icloud_import.json")
PRICE_COLS = ["open", "high", "low", "close", "volume"]
# 겹치는 앞부분 종가가 이 비율 넘게 다르면 수정주가가 바뀐 것으로 본다.
ADJUST_CHECK_ROWS = 20
ADJUST_TOLERANCE = 0.01


def read_manifest(zf: zipfile.ZipFile) -> dict:
    if "manifest.json" not in zf.namelist():
        raise ValueError("manifest.json이 없습니다. KRX_FDR 데이터 묶음이 아닙니다.")
    manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    files = manifest.get("files", {})
    if "raw/daily" not in files or "master" not in files:
        raise ValueError(f"KRX_FDR 데이터 묶음 형식이 아닙니다: {sorted(files)}")
    return manifest


def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def same_frame(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    if len(a) != len(b) or a["date"].tolist() != b["date"].tolist():
        return False
    if a["price_status"].astype(str).tolist() != b["price_status"].astype(str).tolist():
        return False
    left = a[PRICE_COLS].astype(float).to_numpy()
    right = b[PRICE_COLS].astype(float).to_numpy()
    return bool(np.allclose(left, right, rtol=0, atol=1e-6, equal_nan=True))


def adjusted_since(local: pd.DataFrame, incoming: pd.DataFrame) -> bool:
    """겹치는 앞부분 종가가 다르면 액면분할 등으로 과거 가격이 수정된 것이다."""
    first = sorted(set(local["date"]) & set(incoming["date"]))[:ADJUST_CHECK_ROWS]
    old = local.set_index("date").loc[first, "close"].astype(float)
    new = incoming.set_index("date").loc[first, "close"].astype(float)
    valid = (old > 0) & (new > 0)
    return bool(((new[valid] / old[valid] - 1).abs() > ADJUST_TOLERANCE).any())


def merge_raw(local: pd.DataFrame, incoming: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """(합친 결과, 처리 방식)을 돌려준다. 처리 방식이 "same"이면 저장할 필요가 없다."""
    if local.empty:
        return incoming, "new"
    if incoming.empty:
        return local, "same"

    start, end = incoming["date"].min(), incoming["date"].max()
    how = "merged"
    older = local[local["date"] < start]
    if adjusted_since(local, incoming):
        older, how = older.iloc[0:0], "replaced"
    merged = (
        pd.concat([older, incoming, local[local["date"] > end]], ignore_index=True)
          .sort_values("date")
          .reset_index(drop=True)
    )
    if same_frame(merged, local):
        return local, "same"
    return merged, how


def pick_members(zf: zipfile.ZipFile, master_names: dict) -> dict:
    """종목코드별로 가져올 파일 하나를 고른다. 이름이 바뀐 종목은 옛 이름 파일도 함께 들어 있다."""
    picked = {}
    for member in sorted(zf.namelist()):
        if not (member.startswith("data/raw/daily/") and member.endswith(".csv")):
            continue
        code, _, name = os.path.splitext(os.path.basename(member))[0].partition("_")
        if code not in picked or name == master_names.get(code):
            picked[code] = (member, name)
    return picked


def local_raw_path(code: str, name: str) -> str:
    """PC 업데이트와 같은 규칙으로 현재 이름 파일을 쓰고, 없으면 기존 파일을 쓴다."""
    path = raw_file_path(code, name)
    if os.path.exists(path):
        return path
    existing = glob.glob(os.path.join(RAW_DAILY_DIR, f"{glob.escape(code)}_*.csv"))
    return existing[0] if len(existing) == 1 else path


def import_raw(zf: zipfile.ZipFile, work_dir: str, master_names: dict) -> list:
    """일봉 원본을 합치고 파생 데이터를 다시 만들 (코드, 이름) 목록을 돌려준다."""
    picked = pick_members(zf, master_names)
    counts = {"new": 0, "merged": 0, "replaced": 0, "same": 0}
    tasks = []
    for i, (code, (member, zip_name)) in enumerate(sorted(picked.items()), 1):
        local_path = local_raw_path(code, master_names.get(code, zip_name))
        name = os.path.splitext(os.path.basename(local_path))[0].partition("_")[2]

        incoming_path = zf.extract(member, work_dir)
        merged, how = merge_raw(load_raw_daily(local_path), load_raw_daily(incoming_path))
        os.remove(incoming_path)
        counts[how] += 1
        if how != "same":
            save_raw_daily(local_path, merged)
            tasks.append((code, name))
        if how == "replaced":
            print(f"[RAW] {code} {name}: 과거 가격이 수정되어 Mac 데이터로 교체", flush=True)
        if i % 500 == 0 or i == len(picked):
            print(f"[RAW {i}/{len(picked)}] 진행중", flush=True)
    print(f"[RAW] 신규 {counts['new']}, 갱신 {counts['merged']}, 교체 {counts['replaced']}, 변화 없음 {counts['same']}", flush=True)
    return tasks


def copy_members(zf: zipfile.ZipFile, prefix: str, target_dir: str) -> int:
    count = 0
    for member in zf.namelist():
        if not member.startswith(prefix) or member.endswith("/"):
            continue
        target = os.path.join(target_dir, *member[len(prefix):].split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with zf.open(member) as src, open(target + ".tmp", "wb") as dst:
            shutil.copyfileobj(src, dst)
        os.replace(target + ".tmp", target)
        count += 1
    return count


def import_scan(zf: zipfile.ZipFile, manifest: dict) -> None:
    scan = manifest.get("scan")
    if not scan:
        return
    target = os.path.join(config.OUTPUT_DIR, scan)
    if os.path.isdir(target):
        print(f"[SCAN] {scan}: 이미 있음", flush=True)
        return
    work = target + ".importing"
    shutil.rmtree(work, ignore_errors=True)
    count = copy_members(zf, f"output/{scan}/", work)
    os.replace(work, target)
    print(f"[SCAN] {scan}: {count}개 파일 복사", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_path", nargs="?", default=DEFAULT_ZIP)
    parser.add_argument("--force", action="store_true", help="이미 가져온 묶음이어도 다시 합친다.")
    args = parser.parse_args()

    if not os.path.exists(args.zip_path):
        print(f"[ICLOUD] 데이터 묶음이 없습니다: {args.zip_path}", flush=True)
        return 1

    ensure_dirs()
    with tempfile.TemporaryDirectory(prefix="krx_icloud_") as work_dir:
        # iCloud가 동기화 중에 파일을 바꿀 수 있으므로 복사본을 읽는다.
        zip_copy = os.path.join(work_dir, "krx_full_data.zip")
        shutil.copyfile(args.zip_path, zip_copy)
        with zipfile.ZipFile(zip_copy) as zf:
            manifest = read_manifest(zf)
            built_at = manifest.get("built_at", "")
            print(f"[ICLOUD] {built_at} {manifest.get('host', '')} 데이터 묶음", flush=True)

            state = load_state()
            if built_at and state.get("built_at") == built_at and not args.force:
                print("[ICLOUD] 이미 가져온 묶음입니다. 건너뜁니다.", flush=True)
                return 0

            master = pd.read_csv(io.BytesIO(zf.read("data/master/kospi_tickers.csv")), dtype={"code": str})
            master_names = dict(zip(master["code"].str.zfill(6), master["name"].map(safe_filename)))
            tasks = import_raw(zf, work_dir, master_names)
            if tasks:
                generate_derived_all(tasks, total=len(tasks))
            copy_members(zf, "data/master/", os.path.dirname(MASTER_FILE))
            copy_members(zf, "data/index/", INDEX_DIR)
            import_scan(zf, manifest)

    save_state({"built_at": built_at, "scan": manifest.get("scan"), "derived": len(tasks)})
    print("[ICLOUD] 데이터 합치기 완료", flush=True)
    auto_publish.publish_after("iCloud 데이터 가져오기")
    return 0


if __name__ == "__main__":
    sys.exit(main())
