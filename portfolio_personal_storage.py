"""Configured personal-file layout. Market CSV/JSON stays in the project."""
from __future__ import annotations
import hashlib
import json
import os
import re
import uuid
from datetime import date
from pathlib import Path


def json_text(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n"


def directories(project_root):
    project_root = Path(project_root)
    config_file = project_root / "portfolio_storage_config.json"
    if not config_file.exists():
        base = project_root / "portfolio_dashboard_data"
        return {"root": base, "main": base, "daily": base / "daily", "dividends": base / "dividends", "server_url": ""}
    config = json.loads(config_file.read_text(encoding="utf-8-sig"))
    root = Path(config["root"]).resolve()
    if not Path(config["root"]).is_absolute():
        raise ValueError("저장 루트는 절대 경로여야 합니다.")
    result = {"root": root, "server_url": config.get("server_url", "")}
    for key in ("main", "daily", "dividends"):
        relative = Path(config.get(key, key))
        target = (root / relative).resolve()
        if relative.is_absolute() or not target.is_relative_to(root) or target == root:
            raise ValueError("저장 하위 폴더는 지정 루트 안의 별도 폴더여야 합니다.")
        result[key] = target
    if len({result[key] for key in ("main", "daily", "dividends")}) != 3:
        raise ValueError("메인·일별·배당 폴더를 구분하세요.")
    url = result["server_url"]
    if url and not re.fullmatch(r"http://127\.0\.0\.1:\d{1,5}", url):
        raise ValueError("저장 서버 주소는 로컬 루프백이어야 합니다.")
    return result


def public_config(project_root):
    return {"version": 2, **{key: str(value) for key, value in directories(project_root).items()}}


def atomic_bytes(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def receipt_totals(items):
    amounts = {"KRW": 0, "USD": 0}
    known = 0
    missing = 0
    for item in items:
        amount = item["amount"]
        amounts[item["currency"]] += amount
        if item["currency"] == "KRW":
            known += amount
        elif amount == 0:
            pass
        elif item["usd_krw"] is None:
            missing += 1
        else:
            known += amount * item["usd_krw"]
    return {"amounts": amounts, "krw_total": None if missing else known, "known_krw": known, "missing_fx_count": missing}


def monthly_receipts(receipts):
    grouped = {}
    for item in receipts:
        grouped.setdefault(item["received_on"][:7], []).append(item)
    rows = []
    for month, items in sorted(grouped.items()):
        accounts = {}
        for item in items:
            accounts.setdefault(item["account_id"], []).append(item)
        account_rows = [{"account_id": key, "account_name": values[0]["account_name"], "receipt_count": len(values), **receipt_totals(values)} for key, values in sorted(accounts.items())]
        rows.append({"month": month, "receipt_count": len(items), **receipt_totals(items), "accounts": account_rows, "change_krw": None, "change_pct": None, "change_status": "전월 미기록"})
    lookup = {row["month"]: row for row in rows}
    for row in rows:
        year, month = map(int, row["month"].split("-"))
        previous = lookup.get(f"{year if month > 1 else year - 1:04d}-{month - 1 if month > 1 else 12:02d}")
        if not previous:
            continue
        if row["krw_total"] is None or previous["krw_total"] is None:
            row["change_status"] = "환율 미입력"
            continue
        row["change_krw"] = row["krw_total"] - previous["krw_total"]
        row["change_pct"] = row["change_krw"] / previous["krw_total"] * 100 if previous["krw_total"] > 0 else None
        row["change_status"] = "전월 0원" if previous["krw_total"] == 0 else ""
    return rows


def envelope(doc, data):
    return {"format_version": 1, "generated_by": "krx-portfolio", "document_id": doc["document_id"], "revision": doc["revision"], "data": data}


def write_bundle(project_root, doc, content, previous_text=None, writer=None):
    """Commit canonical JSON last; roll back projections if any write fails."""
    dirs = directories(project_root)
    main = dirs["main"] / "portfolio.json"
    outputs = {}
    def add(path, data, archive=False):
        raw = json_text(envelope(doc, data)).encode("utf-8")
        if path.exists():
            old_raw = path.read_bytes()
            try:
                old = json.loads(old_raw.decode("utf-8-sig"))
                if old.get("document_id") == doc["document_id"] and old.get("data") == data:
                    raw = old_raw
                elif archive:
                    digest = hashlib.sha256(old_raw).hexdigest()[:12]
                    outputs[path.parent / "archive" / f"{path.stem}_r{old.get('revision', 'legacy')}_{digest}.json"] = old_raw
            except (ValueError, AttributeError):
                if archive:
                    digest = hashlib.sha256(old_raw).hexdigest()[:12]
                    outputs[path.parent / "archive" / f"{path.stem}_legacy_{digest}.json"] = old_raw
        outputs[path] = raw
    snapshots = doc["snapshots"]
    dates = set()
    for snapshot in snapshots:
        day = snapshot.get("date", "")
        if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or day in dates:
            raise ValueError("일별 평가 기록의 날짜를 확인하세요.")
        date.fromisoformat(day)
        dates.add(day)
        add(dirs["daily"] / (day + ".json"), {"snapshot": snapshot}, archive=True)
    add(dirs["daily"] / "daily_records.json", {"snapshots": snapshots})
    receipts = doc.get("dividend_receipts", [])
    monthly = monthly_receipts(receipts)
    add(dirs["dividends"] / "receipts.json", {"dividend_receipts": receipts})
    add(dirs["dividends"] / "monthly_summary.json", {"months": monthly})
    add(dirs["dividends"] / "expected_dividends.json", {"holdings": [{key: h.get(key) for key in ("id", "account_id", "code", "name", "currency", "quantity", "dividend")} for h in doc["holdings"] if "dividend" in h]})
    months = set()
    for row in monthly:
        month = row["month"]
        months.add(month)
        add(dirs["dividends"] / (month + ".json"), {"month": month, "receipts": [r for r in receipts if r["received_on"].startswith(month)], "summary": row}, archive=True)
    # Retain corrections and clear obsolete generated projections after an explicit import/deletion.
    for folder, pattern, present, key in ((dirs["daily"], r"\d{4}-\d{2}-\d{2}\.json", dates, "snapshot"), (dirs["dividends"], r"\d{4}-\d{2}\.json", months, "summary")):
        if folder.exists():
            for old_path in folder.glob("*.json"):
                if not re.fullmatch(pattern, old_path.name) or old_path.stem in present:
                    continue
                old = json.loads(old_path.read_text(encoding="utf-8-sig"))
                if old.get("generated_by") == "krx-portfolio":
                    data = {"snapshot": None, "removed": True} if key == "snapshot" else {"month": old_path.stem, "receipts": [], "summary": None, "removed": True}
                    add(old_path, data, archive=True)
    canonical = content.encode("utf-8")
    manifest = {"version": 2, "document_id": doc["document_id"], "revision": doc["revision"], "canonical": str(main), "canonical_sha256": hashlib.sha256(canonical).hexdigest(), "files": [{"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()} for path, raw in outputs.items()]}
    outputs[dirs["main"] / "storage_manifest.json"] = json_text(manifest).encode("utf-8")
    if previous_text is not None:
        outputs[dirs["main"] / "portfolio.previous.json"] = previous_text.encode("utf-8")
    outputs[main] = canonical
    old_values = {path: path.read_bytes() if path.exists() else None for path in outputs}
    changed = []
    try:
        for path, raw in outputs.items():
            if old_values[path] == raw:
                continue
            changed.append(path)
            if writer is None:
                atomic_bytes(path, raw)
            else:
                writer(path, raw.decode("utf-8"))
    except Exception:
        for path in reversed(changed):
            if old_values[path] is None:
                if path.exists():
                    path.unlink()
            else:
                atomic_bytes(path, old_values[path])
        raise
    return {"path": str(main), "paths": public_config(project_root)}


def export_file(project_root, request):
    name, kind, content = request.get("name"), request.get("kind"), request.get("content")
    if not isinstance(name, str) or not isinstance(content, str) or len(content.encode("utf-8")) > 50 * 1024 * 1024:
        raise ValueError("내보낼 파일의 이름·크기를 확인하세요.")
    allowed = {"main": r"(?:krx_portfolio_\d{4}-\d{2}-\d{2}_r\d+\.json|krx_holdings_\d{4}-\d{2}-\d{2}\.csv)", "dividends": r"dividend_(?:receipts|monthly)_\d{4}-\d{2}-\d{2}\.csv"}
    if kind not in allowed or not re.fullmatch(allowed[kind], name):
        raise ValueError("허용된 포트폴리오 파일만 내보낼 수 있습니다.")
    folder = directories(project_root)[kind] / "exports"
    target = folder / name
    raw = content.encode("utf-8")
    if target.exists() and target.read_bytes() != raw:
        target = folder / f"{target.stem}_{hashlib.sha256(raw).hexdigest()[:12]}{target.suffix}"
    atomic_bytes(target, raw)
    return {"path": str(target), "sha256": hashlib.sha256(raw).hexdigest()}
