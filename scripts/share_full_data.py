# scripts/share_full_data.py
"""전체 데이터를 zip 하나로 묶어 공유 폴더(iCloud Drive)에 두고, 다른 PC에서 받아 설치한다.

    python scripts/share_full_data.py export   # 스캔한 PC: 묶음 만들기
    python scripts/share_full_data.py import   # 다른 PC: 묶음 설치 (pull.cmd)

보유·관심·패턴 기록(tracking)과 로그(logs)는 묶지도 덮어쓰지도 않는다.
"""

import argparse
import json
import os
import shutil
import socket
import sys
import tempfile
import zipfile
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import DATA_DIR, OUTPUT_DIR  # noqa: E402

BUNDLE_NAME = "krx_full_data.zip"
MANIFEST_NAME = "krx_full_data.json"
IMPORTED_MARKER = "shared_import.json"

# DATA_DIR 아래에서 통째로 교체하는 폴더. tracking, logs는 포함하지 않는다.
MANAGED_DIRS = [
    "master",
    os.path.join("raw", "daily"),
    os.path.join("derived", "daily"),
    os.path.join("derived", "weekly"),
    os.path.join("derived", "monthly"),
    "index",
]
STORED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".zip", ".parquet"}


def default_share_dir() -> str:
    env = os.getenv("KRX_SHARE_DIR")
    if env:
        return env
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Mobile Documents", "com~apple~CloudDocs", "KRX_FDR")
    # iCloud for Windows 기본 위치
    return os.path.join(os.getenv("USERPROFILE", home), "iCloudDrive", "KRX_FDR")


def latest_scan_dir(output_dir: str):
    if not os.path.isdir(output_dir):
        return None
    scans = sorted(d for d in os.listdir(output_dir) if d.startswith("scan_result_"))
    return os.path.join(output_dir, scans[-1]) if scans else None


def _arcname(path: str, base: str, prefix: str) -> str:
    return prefix + "/" + os.path.relpath(path, base).replace(os.sep, "/")


def _add_tree(bundle: zipfile.ZipFile, folder: str, base: str, prefix: str) -> int:
    count = 0
    for root, _, files in os.walk(folder):
        for name in sorted(files):
            if name.startswith(".") or name.endswith((".partial", ".tmp")):
                continue
            path = os.path.join(root, name)
            ext = os.path.splitext(name)[1].lower()
            compress = zipfile.ZIP_STORED if ext in STORED_EXTENSIONS else zipfile.ZIP_DEFLATED
            bundle.write(path, _arcname(path, base, prefix), compress_type=compress)
            count += 1
    return count


def export_bundle(share_dir: str) -> dict:
    scan_dir = latest_scan_dir(OUTPUT_DIR)
    os.makedirs(share_dir, exist_ok=True)
    target = os.path.join(share_dir, BUNDLE_NAME)
    # 공유 폴더에 쓰다 만 파일이 동기화되지 않도록 로컬 임시 폴더에서 만든 뒤 옮긴다.
    with tempfile.TemporaryDirectory() as temp_dir:
        local_zip = os.path.join(temp_dir, BUNDLE_NAME)
        counts = {}
        with zipfile.ZipFile(local_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
            for rel in MANAGED_DIRS:
                folder = os.path.join(DATA_DIR, rel)
                counts[rel.replace(os.sep, "/")] = _add_tree(bundle, folder, DATA_DIR, "data") if os.path.isdir(folder) else 0
            if scan_dir:
                counts["scan"] = _add_tree(bundle, scan_dir, OUTPUT_DIR, "output")
            manifest = {
                "built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "host": socket.gethostname(),
                "scan": os.path.basename(scan_dir) if scan_dir else None,
                "files": counts,
            }
            bundle.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        manifest["size_mb"] = round(os.path.getsize(local_zip) / 1e6, 1)
        partial = target + ".partial"
        shutil.copyfile(local_zip, partial)
        os.replace(partial, target)
    with open(os.path.join(share_dir, MANIFEST_NAME), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest


def _safe_members(bundle: zipfile.ZipFile):
    for info in bundle.infolist():
        name = info.filename
        if name.startswith("/") or ".." in name.split("/") or ":" in name:
            raise ValueError(f"잘못된 경로가 묶음에 있습니다: {name}")
        yield info


def import_bundle(share_dir: str, force: bool = False) -> dict:
    source = os.path.join(share_dir, BUNDLE_NAME)
    if not os.path.exists(source):
        raise SystemExit(f"공유 묶음이 없습니다: {source}")

    with zipfile.ZipFile(source) as bundle:
        manifest = json.loads(bundle.read("manifest.json").decode("utf-8"))
        marker = os.path.join(DATA_DIR, IMPORTED_MARKER)
        if not force and os.path.exists(marker):
            with open(marker, encoding="utf-8") as f:
                if json.load(f).get("built_at") == manifest["built_at"]:
                    print(f"이미 최신입니다 (묶음 생성 {manifest['built_at']}). 다시 설치하려면 --force")
                    return None

        # 같은 드라이브의 임시 폴더에 먼저 풀어서, 실패해도 기존 데이터를 건드리지 않는다.
        parent = os.path.dirname(os.path.abspath(DATA_DIR))
        staging = tempfile.mkdtemp(prefix=".krx_import_", dir=parent)
        try:
            members = [m for m in _safe_members(bundle) if m.filename != "manifest.json"]
            for i, member in enumerate(members, start=1):
                bundle.extract(member, staging)
                if i % 2000 == 0:
                    print(f"  압축 해제 {i:,}/{len(members):,}")

            for rel in MANAGED_DIRS:
                new_dir = os.path.join(staging, "data", rel)
                if not os.path.isdir(new_dir):
                    continue
                current = os.path.join(DATA_DIR, rel)
                old = current + ".old_import"
                if os.path.exists(old):
                    shutil.rmtree(old)
                os.makedirs(os.path.dirname(current), exist_ok=True)
                if os.path.exists(current):
                    os.replace(current, old)
                os.replace(new_dir, current)
                if os.path.exists(old):
                    shutil.rmtree(old)

            scan = manifest.get("scan")
            if scan:
                new_scan = os.path.join(staging, "output", scan)
                dest_scan = os.path.join(OUTPUT_DIR, scan)
                if os.path.isdir(new_scan) and not os.path.exists(dest_scan):
                    os.makedirs(OUTPUT_DIR, exist_ok=True)
                    os.replace(new_scan, dest_scan)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    with open(os.path.join(DATA_DIR, IMPORTED_MARKER), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="전체 데이터를 공유 폴더(iCloud Drive)로 내보내거나 가져옵니다.")
    parser.add_argument("action", choices=["export", "import"])
    parser.add_argument("--dir", default=None, help="공유 폴더 (기본: iCloud Drive/KRX_FDR, 환경변수 KRX_SHARE_DIR)")
    parser.add_argument("--force", action="store_true", help="import: 이미 설치한 묶음이라도 다시 설치")
    args = parser.parse_args()
    share_dir = args.dir or default_share_dir()

    if args.action == "export":
        print(f"전체 데이터 묶음 생성 → {share_dir}")
        m = export_bundle(share_dir)
        print(f"완료: {m['size_mb']}MB, 스캔 {m['scan']}, 파일 {m['files']}")
    else:
        print(f"전체 데이터 묶음 설치 ← {share_dir}")
        print(f"설치 위치: {DATA_DIR}")
        m = import_bundle(share_dir, force=args.force)
        if m:
            print(f"완료: 묶음 생성 {m['built_at']} ({m.get('host')}), 스캔 {m['scan']}")


if __name__ == "__main__":
    main()
