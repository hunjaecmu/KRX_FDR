"""서버용 경량 버전의 데이터 묶음을 만들고 GitHub Release에서 주고받는다. Streamlit에 의존하지 않는다."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime
from typing import Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

import data_loader
from config import INDEX_TICKERS

BUNDLE_NAME = "krx_lite_data.zip"
RELEASE_TAG = "lite-data"
DEFAULT_API = "https://api.github.com"
DEFAULT_UPLOADS = "https://uploads.github.com"
REQUEST_TIMEOUT = 60
STRING_COLUMNS = ["asof_datetime", "asof_date", "asof_time", "price_status"]


def _manifest_path(data_dir: str) -> str:
    return os.path.join(data_dir, "lite", "manifest.json")


def _synced_asset_path(data_dir: str) -> str:
    return os.path.join(data_dir, "lite", "synced_asset.txt")


def load_manifest(data_dir: str) -> Optional[dict]:
    path = _manifest_path(data_dir)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def latest_scan_dir(output_dir: str) -> Optional[str]:
    if not os.path.isdir(output_dir):
        return None
    names = [
        name for name in os.listdir(output_dir)
        if name.startswith("scan_result_") and os.path.isdir(os.path.join(output_dir, name))
    ]
    return os.path.join(output_dir, sorted(names)[-1]) if names else None


def available_indices() -> list[str]:
    return [
        code for code, _ in INDEX_TICKERS
        if data_loader._find_file(data_loader.INDEX_WEEKLY_DIR, code) is not None
    ]


def load_index_summaries(data_dir: str) -> list[dict]:
    summaries = []
    for code, _ in INDEX_TICKERS:
        path = os.path.join(data_dir, "index", f"{code}_summary.json")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                summaries.append(json.load(f))
    return summaries


def write_prices_parquet(data_dir: str, master: pd.DataFrame, target_path: str) -> int:
    frames = []
    for code in master["code"]:
        for timeframe, folder in (("weekly", data_loader.DERIVED_WEEKLY_DIR), ("monthly", data_loader.DERIVED_MONTHLY_DIR)):
            file_path = data_loader._find_file(folder, code)
            if file_path is None:
                continue
            frame = pd.read_csv(file_path)
            frame["code"] = code
            frame["timeframe"] = timeframe
            frames.append(frame)

    for code in available_indices():
        for timeframe, folder in (("weekly", data_loader.INDEX_WEEKLY_DIR), ("monthly", data_loader.INDEX_MONTHLY_DIR)):
            file_path = data_loader._find_file(folder, code)
            if file_path is None:
                continue
            frame = pd.read_csv(file_path)
            frame["code"] = code
            frame["timeframe"] = timeframe
            frames.append(frame)

    prices = pd.concat(frames, ignore_index=True)
    prices["is_final"] = prices["is_final"].astype(str).str.lower()
    for column in STRING_COLUMNS:
        if column in prices.columns:
            prices[column] = prices[column].astype("string")
    prices = prices.sort_values(["timeframe", "code", "date"]).reset_index(drop=True)

    # 종목별 조회가 필요한 행 묶음만 읽도록 코드순으로 잘게 나눠 저장한다.
    table = pa.Table.from_pandas(prices, preserve_index=False)
    pq.write_table(table, target_path, compression="zstd", row_group_size=2000)
    return len(prices)


def build_bundle(data_dir: str, output_dir: str, data_status: dict, target_path: str) -> dict:
    scan_dir = latest_scan_dir(output_dir)
    if scan_dir is None:
        raise FileNotFoundError(f"스캔 결과가 없습니다: {output_dir}")

    master_path = os.path.join(data_dir, "master", "kospi_tickers.csv")
    master = data_loader.load_master()
    if master.empty:
        raise FileNotFoundError(f"종목 마스터가 없습니다: {master_path}")

    manifest = {
        "built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scan": os.path.basename(scan_dir),
        "indices": available_indices(),
        "index_summaries": load_index_summaries(data_dir),
        "data_status": data_status,
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        parquet_path = os.path.join(temp_dir, "prices.parquet")
        manifest["price_rows"] = write_prices_parquet(data_dir, master, parquet_path)

        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        partial_path = target_path + ".partial"
        with zipfile.ZipFile(partial_path, "w", zipfile.ZIP_STORED) as bundle:
            bundle.write(master_path, "data/master/kospi_tickers.csv", zipfile.ZIP_DEFLATED)
            bundle.write(parquet_path, "data/lite/prices.parquet")
            for root, _, files in os.walk(scan_dir):
                for name in files:
                    full_path = os.path.join(root, name)
                    relative = os.path.relpath(full_path, os.path.dirname(scan_dir)).replace(os.sep, "/")
                    bundle.write(full_path, f"output/{relative}")
            bundle.writestr("data/lite/manifest.json", json.dumps(manifest, ensure_ascii=False))
        os.replace(partial_path, target_path)
    return manifest


def _headers(token: Optional[str], accept: str = "application/vnd.github+json") -> dict:
    headers = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _safe_extract(bundle: zipfile.ZipFile, target_dir: str) -> None:
    root = os.path.realpath(target_dir)
    for member in bundle.namelist():
        destination = os.path.realpath(os.path.join(target_dir, member))
        if os.path.commonpath([root, destination]) != root:
            raise ValueError(f"잘못된 묶음 경로: {member}")
    bundle.extractall(target_dir)


def install_bundle(bundle_path: str, data_dir: str, output_dir: str, asset_id: object = "") -> None:
    work_parent = os.path.dirname(os.path.abspath(data_dir))
    os.makedirs(work_parent, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work_parent, prefix=".lite_install_") as work_dir:
        with zipfile.ZipFile(bundle_path) as bundle:
            _safe_extract(bundle, work_dir)

        for name in ("master", "lite"):
            target = os.path.join(data_dir, name)
            os.makedirs(data_dir, exist_ok=True)
            if os.path.isdir(target):
                shutil.rmtree(target)
            shutil.move(os.path.join(work_dir, "data", name), target)

        os.makedirs(output_dir, exist_ok=True)
        for name in os.listdir(output_dir):
            if name.startswith("scan_result_"):
                shutil.rmtree(os.path.join(output_dir, name))
        for name in os.listdir(os.path.join(work_dir, "output")):
            shutil.move(os.path.join(work_dir, "output", name), os.path.join(output_dir, name))

    with open(_synced_asset_path(data_dir), "w", encoding="utf-8") as f:
        f.write(str(asset_id))


def _synced_asset(data_dir: str) -> Optional[str]:
    path = _synced_asset_path(data_dir)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def ensure_data(repo: str, token: Optional[str], data_dir: str, output_dir: str, api: str = DEFAULT_API) -> bool:
    """새 묶음이 있으면 내려받아 설치한다. 조회에 실패해도 기존 데이터가 있으면 그대로 쓴다."""
    try:
        response = requests.get(
            f"{api}/repos/{repo}/releases/tags/{RELEASE_TAG}",
            headers=_headers(token),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        assets = [a for a in response.json().get("assets", []) if a.get("name") == BUNDLE_NAME]
        if not assets:
            raise FileNotFoundError(f"{repo}의 {RELEASE_TAG} 릴리스에 {BUNDLE_NAME}이 없습니다.")

        asset = assets[0]
        if _synced_asset(data_dir) == str(asset["id"]):
            return False

        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_path = os.path.join(temp_dir, BUNDLE_NAME)
            with requests.get(
                f"{api}/repos/{repo}/releases/assets/{asset['id']}",
                headers=_headers(token, accept="application/octet-stream"),
                stream=True,
                timeout=REQUEST_TIMEOUT,
            ) as download:
                download.raise_for_status()
                with open(bundle_path, "wb") as f:
                    for chunk in download.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
            install_bundle(bundle_path, data_dir, output_dir, asset["id"])
        return True
    except (requests.RequestException, OSError, ValueError, zipfile.BadZipFile):
        if load_manifest(data_dir) is None:
            raise
        return False


def _check_github_response(response: requests.Response, action: str) -> None:
    if response.ok:
        return
    try:
        body = response.json()
        detail = body.get("message", "")
        errors = body.get("errors")
        if errors:
            detail = f"{detail} {errors}"
    except ValueError:
        detail = response.text[:200]
    raise RuntimeError(f"GitHub {action} 실패 (HTTP {response.status_code}): {detail}")


def upload_bundle(
    bundle_path: str,
    repo: str,
    token: str,
    api: str = DEFAULT_API,
    uploads: str = DEFAULT_UPLOADS,
) -> str:
    """lite-data 릴리스의 묶음 파일을 새 파일로 교체하고 릴리스 주소를 돌려준다."""
    response = requests.get(
        f"{api}/repos/{repo}/releases/tags/{RELEASE_TAG}", headers=_headers(token), timeout=REQUEST_TIMEOUT
    )
    if response.status_code == 404:
        response = requests.post(
            f"{api}/repos/{repo}/releases",
            headers=_headers(token),
            json={"tag_name": RELEASE_TAG, "name": "KRX lite data"},
            timeout=REQUEST_TIMEOUT,
        )
    _check_github_response(response, "릴리스 조회/생성")
    release = response.json()

    # 업로드 실패 시 기존 파일이 남도록 임시 이름으로 올린 뒤 교체한다.
    temp_name = f"upload_{datetime.now().strftime('%Y%m%d%H%M%S')}.zip"
    with open(bundle_path, "rb") as f:
        uploaded = requests.post(
            f"{uploads}/repos/{repo}/releases/{release['id']}/assets",
            params={"name": temp_name},
            headers={**_headers(token), "Content-Type": "application/zip"},
            data=f,
            timeout=None,
        )
    _check_github_response(uploaded, "파일 업로드")
    new_asset = uploaded.json()

    for asset in release.get("assets", []):
        deleted = requests.delete(
            f"{api}/repos/{repo}/releases/assets/{asset['id']}", headers=_headers(token), timeout=REQUEST_TIMEOUT
        )
        _check_github_response(deleted, "기존 파일 삭제")
    renamed = requests.patch(
        f"{api}/repos/{repo}/releases/assets/{new_asset['id']}",
        headers=_headers(token),
        json={"name": BUNDLE_NAME},
        timeout=REQUEST_TIMEOUT,
    )
    _check_github_response(renamed, "파일 이름 변경")
    return str(release.get("html_url", ""))
