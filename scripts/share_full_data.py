# scripts/share_full_data.py
"""스캔한 PC의 데이터를 공유 폴더(iCloud Drive)로 보내고, 다른 PC에서 받아 반영한다.

    python scripts/share_full_data.py export   # 스캔한 PC: 일일 시세 파일 복사 (+ 주 1회 전체 묶음)
    python scripts/share_full_data.py import   # 다른 PC: 일일 시세 파일 반영 후 스캔 (pull.cmd)

공유 폴더
    daily_close/YYYYMMDD_HHMMSS.zip   업데이트마다 생기는 일일 시세 파일 (수백 KB, 60일 보관)
    krx_full_data.zip                 전체 데이터 묶음 (약 500MB, 7일마다 갱신). 처음 받을 때와
                                      일일 시세 파일이 끊겼을 때만 쓴다.

보유·관심·패턴 기록(tracking)과 로그(logs)는 묶지도 덮어쓰지도 않는다.
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import DATA_DIR, OUTPUT_DIR  # noqa: E402
import data_store as ds  # noqa: E402

BUNDLE_NAME = "krx_full_data.zip"
MANIFEST_NAME = "krx_full_data.json"
IMPORTED_MARKER = "shared_import.json"
DAILY_SUBDIR = "daily_close"
EXPORT_STATUS = "krx_last_export.json"
FULL_REFRESH_DAYS = 7

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
            local_deltas = ds.list_daily_close()
            manifest = {
                "built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "host": socket.gethostname(),
                # 이 묶음에 이미 반영된 마지막 일일 시세 파일. 받는 쪽은 이후 파일만 반영한다.
                "last_delta": _delta_id(local_deltas[-1]) if local_deltas else None,
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


def find_bundle(share_dir: str):
    """전체 묶음 경로. iCloud for Windows가 충돌로 'krx_full_data(1).zip'처럼 이름을 바꿔 두는 경우도 찾는다."""
    exact = os.path.join(share_dir, BUNDLE_NAME)
    if os.path.exists(exact):
        return exact
    stem = os.path.splitext(BUNDLE_NAME)[0]
    variants = [os.path.join(share_dir, n) for n in os.listdir(share_dir)
                if n.startswith(stem) and n.endswith(".zip") and not n.endswith(".partial")] if os.path.isdir(share_dir) else []
    # 가장 최근에 받은 파일이 manifest와 맞는 최신 묶음이다.
    return max(variants, key=os.path.getmtime) if variants else None


def import_bundle(share_dir: str) -> dict:
    """전체 묶음을 설치한다. 실패하면 기존 데이터를 그대로 둔다."""
    source = find_bundle(share_dir)
    if not source:
        raise SystemExit(f"공유 묶음이 없습니다: {os.path.join(share_dir, BUNDLE_NAME)}")

    with zipfile.ZipFile(source) as bundle:
        manifest = json.loads(bundle.read("manifest.json").decode("utf-8"))
        print(f"전체 묶음 설치: 생성 {manifest['built_at']} ({manifest.get('host')})")

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

    return manifest


def _delta_id(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _copy_atomic(source: str, target: str) -> None:
    partial = target + ".partial"
    shutil.copyfile(source, partial)
    os.replace(partial, target)


def export_share(share_dir: str, full: bool = False) -> dict:
    """일일 시세 파일을 공유 폴더로 복사하고, 필요할 때만 전체 묶음을 다시 만든다."""
    daily_dir = os.path.join(share_dir, DAILY_SUBDIR)
    os.makedirs(daily_dir, exist_ok=True)

    copied = []
    for path in ds.list_daily_close():
        target = os.path.join(daily_dir, os.path.basename(path))
        if not os.path.exists(target) or os.path.getsize(target) != os.path.getsize(path):
            _copy_atomic(path, target)
            copied.append(os.path.basename(path))
    ds.prune_daily_close(daily_dir)

    current = _read_json(os.path.join(share_dir, MANIFEST_NAME))
    reason = None
    if full:
        reason = "요청"
    elif not current or not os.path.exists(os.path.join(share_dir, BUNDLE_NAME)):
        reason = "없음"
    elif "last_delta" not in current:
        reason = "이전 형식"
    else:
        age = datetime.now() - datetime.strptime(current["built_at"], "%Y-%m-%d %H:%M:%S")
        if age.days >= FULL_REFRESH_DAYS - 1:
            reason = f"{age.days}일 경과"
        elif current["last_delta"] and not os.path.exists(os.path.join(daily_dir, current["last_delta"] + ".zip")):
            reason = "보관 기간 지남"

    full_manifest = export_bundle(share_dir) if reason else current
    status = {
        "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "daily_copied": copied,
        "daily_kb": round(sum(os.path.getsize(os.path.join(daily_dir, f)) for f in copied) / 1e3, 1),
        "full_rebuilt": reason,
        "full_mb": full_manifest.get("size_mb") if full_manifest else None,
    }
    with open(os.path.join(share_dir, EXPORT_STATUS), "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    return status


def _shared_chain(daily_dir: str) -> list:
    """공유 폴더의 일일 시세 파일 목록: [(id, prev, path)] 이름순."""
    chain = []
    for path in ds.list_daily_close(daily_dir):
        try:
            prev = ds.read_daily_close_manifest(path).get("prev")
        except Exception as e:
            print(f"[WARN] 일일 시세 파일을 읽지 못했습니다 (동기화 중일 수 있음): {os.path.basename(path)} {e}")
            break
        chain.append((_delta_id(path), prev, path))
    return chain


def _pending_after(chain: list, last: str):
    """last 다음부터 끊김 없이 이어지는 파일 목록. 이어지지 않으면 None."""
    ids = [c[0] for c in chain]
    if last is None:
        return None
    if last not in ids:
        # 마지막으로 반영한 파일이 보관 기간이 지나 지워졌어도 다음 파일이 그것을 가리키면 이어진다.
        later = [c for c in chain if c[0] > last]
        if later and later[0][1] == last:
            pending = later
        elif not later and (not ids or last > ids[-1]):
            return []
        else:
            return None
    else:
        pending = chain[ids.index(last) + 1:]
    expected = last
    for delta_id, prev, _ in pending:
        if prev != expected:
            return None
        expected = delta_id
    return pending


def _write_marker(state: dict) -> None:
    path = os.path.join(DATA_DIR, IMPORTED_MARKER)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(path + ".tmp", path)


def import_share(share_dir: str, force_full: bool = False, scan: bool = True) -> bool:
    """공유 폴더에서 아직 반영하지 않은 일일 시세 파일을 반영한다. 반영한 것이 있으면 True."""
    ds.ensure_dirs()
    state = _read_json(os.path.join(DATA_DIR, IMPORTED_MARKER)) or {}
    chain = _shared_chain(os.path.join(share_dir, DAILY_SUBDIR))

    pending = None if force_full else _pending_after(chain, state.get("last_delta"))
    installed_full = False
    if pending is None:
        full = _read_json(os.path.join(share_dir, MANIFEST_NAME))
        if not full or "last_delta" not in full:
            raise SystemExit("공유 폴더에 쓸 수 있는 전체 묶음이 없습니다. Mac에서 export --full 을 실행하세요.")
        if force_full or full.get("built_at") != state.get("full_built_at"):
            full = import_bundle(share_dir)
            installed_full = True
            state = {"full_built_at": full["built_at"], "last_delta": full.get("last_delta")}
            _write_marker(state)
        pending = _pending_after(chain, full.get("last_delta")) if full.get("last_delta") else [c for c in chain]
        if pending is None:
            raise SystemExit(
                "전체 묶음 이후의 일일 시세 파일이 이어지지 않습니다. "
                "iCloud 동기화가 끝났는지 확인하거나, Mac에서 export --full 을 실행하세요."
            )

    if not pending:
        if not installed_full:
            print(f"이미 최신입니다 (마지막 반영 {state.get('last_delta')}).")
            return False
    else:
        touched = {}
        for delta_id, _, path in pending:
            rows = ds.read_daily_close_rows(path)
            res = ds.apply_daily_rows(rows)
            ds.install_daily_close_extras(path)
            bad = [c for c, r in res.items() if r["status"] != "ok"]
            for code, r in res.items():
                if r["status"] == "ok":
                    touched[code] = r["name"]
            print(f"반영: {delta_id} ({len(res):,}종목" + (f", 실패 {len(bad)}: {', '.join(bad[:10])}" if bad else "") + ")")

        print(f"파생 데이터 계산: {len(touched):,}종목")
        ds.generate_derived_all(sorted(touched.items()), total=len(touched))
        state["last_delta"] = pending[-1][0]
        state["applied_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _write_marker(state)

    if scan and pending:
        print("이평 돌파 스캔 실행")
        subprocess.run([sys.executable, "-u", os.path.join(PROJECT_ROOT, "scripts", "scan_market.py")], check=True)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="데이터를 공유 폴더(iCloud Drive)로 내보내거나 가져옵니다.")
    parser.add_argument("action", choices=["export", "import"])
    parser.add_argument("--dir", default=None, help="공유 폴더 (기본: iCloud Drive/KRX_FDR, 환경변수 KRX_SHARE_DIR)")
    parser.add_argument("--full", action="store_true", help="export: 전체 묶음도 지금 다시 만들기 / import: 전체 묶음부터 다시 설치")
    parser.add_argument("--force", action="store_true", help="--full 과 같음 (이전 이름)")
    parser.add_argument("--no-scan", action="store_true", help="import: 반영 후 스캔하지 않기")
    args = parser.parse_args()
    share_dir = args.dir or default_share_dir()
    full = args.full or args.force

    if args.action == "export":
        print(f"공유 폴더로 내보내기 → {share_dir}")
        st = export_share(share_dir, full=full)
        print(f"일일 시세 파일 {len(st['daily_copied'])}개 복사 ({st['daily_kb']}KB)")
        if st["full_rebuilt"]:
            print(f"전체 묶음 다시 만듦 ({st['full_rebuilt']}): {st['full_mb']}MB")
    else:
        print(f"공유 폴더에서 가져오기 ← {share_dir}")
        print(f"설치 위치: {DATA_DIR}")
        if import_share(share_dir, force_full=full, scan=not args.no_scan):
            print("완료")


if __name__ == "__main__":
    main()
