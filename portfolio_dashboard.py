"""Local HTML adapter for this project's data_loader/data_store CSV layout.

Existing master/raw/derived files are read only. Generated files live alongside
the HTML in portfolio_dashboard_data/. No third party dependency is needed to
export; optional online refresh uses the project's installed FinanceDataReader.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import subprocess
import sys
import threading
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent
CODE = re.compile(r"[0-9A-Za-z]{6}\Z")
BUILD_LOCK = threading.Lock()


def now_text():
    return datetime.now(KST).isoformat(timespec="seconds")


def data_directory(root=ROOT):
    # Matches config.py's APP_DATA_DIR / DATA_DIR settings without importing its
    # directory-creation side effects during read-only HTML generation.
    app_dir = Path(os.environ.get("APP_DATA_DIR", str(root / ".app_data")))
    return Path(os.environ.get("DATA_DIR", str(app_dir / "data")))


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def script_json(value):
    return dumps(value).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def atomic_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(content, encoding="utf-8")
    os.replace(temp, path)


def numeric(value):
    try:
        number = float(value)
        if math.isfinite(number):
            return int(number) if number.is_integer() else number
    except (ValueError, TypeError):
        pass
    return None


def load_symbols(data_dir):
    path = data_dir / "master" / "kospi_tickers.csv"
    if not path.is_file():
        raise FileNotFoundError(f"종목 마스터가 없습니다: {path}. 기존 scripts/update_data.py를 먼저 실행하세요.")
    symbols = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            code = str(row.get("code", "")).strip().zfill(6)
            market = str(row.get("market", "")).strip().upper()
            if CODE.fullmatch(code) and (market == "KOSPI" or market.startswith("KOSDAQ")):
                symbols[code] = {"code": code, "name": row.get("name", code),
                                 "market": "KOSDAQ" if market.startswith("KOSDAQ") else market,
                                 "market_detail": market, "currency": "KRW"}
    if not symbols:
        raise ValueError("KOSPI/KOSDAQ 종목 마스터가 비어 있습니다.")
    return sorted(symbols.values(), key=lambda row: row["code"])


def read_prices(path):
    rows = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            day = str(row.get("date", ""))[:10]
            try:
                date.fromisoformat(day)
            except ValueError:
                continue
            close = numeric(row.get("close"))
            if close is None or close <= 0:
                continue
            rows[day] = ([day, close, numeric(row.get("volume"))],
                         {"source_asof": row.get("asof_datetime") or None,
                          "source_status": row.get("price_status") or "미확인"})
    if not rows:
        raise ValueError("유효한 가격이 없습니다.")
    ordered = sorted(rows)
    points = [rows[day][0] for day in ordered]
    metadata = rows[ordered[-1]][1]
    metadata.update({"first_date": ordered[0], "last_date": ordered[-1], "rows": len(points),
                     "price_basis": "기존 FDR 저장 가격 · 조정 기준 미확인",
                     "zero_volume_note": "기존 data_store의 거래량 0 봉 보정이 포함될 수 있음"})
    return points, metadata


def write_history(path, code, points, metadata):
    atomic_text(path, f"window.KRX_HISTORY=window.KRX_HISTORY||{{}};window.KRX_HISTORY[{dumps(code)}]="
                + script_json({"code": code, "points": points, "meta": metadata}) + ";\n")


def summary(symbol, points, metadata):
    result = dict(symbol)
    previous = points[-2][1] if len(points) > 1 else None
    latest = points[-1][1]
    result.update({"price": latest, "previous_price": previous,
                   "change_pct": (latest / previous - 1) * 100 if previous else None,
                   "comparison_date": points[-2][0] if previous else None,
                   "date": points[-1][0], "volume": points[-1][2], "meta": metadata})
    return result


def export_dashboard(data_dir=None, output_dir=ROOT):
    data_dir = Path(data_dir) if data_dir else data_directory()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "portfolio_dashboard_data"
    history_dir = target / "history"
    symbols = load_symbols(data_dir)
    files = {}
    for candidate in sorted((data_dir / "raw" / "daily").glob("*.csv")):
        code = candidate.name.split("_", 1)[0]
        if code in files:
            # Do not silently choose a renamed/duplicate ticker's arbitrary CSV.
            files[code] = None
        else:
            files[code] = candidate
    manifest_path = target / "manifest.json"
    old_manifest = {}
    if manifest_path.is_file():
        try:
            old_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    manifest, result, issues = {}, [], []
    for symbol in symbols:
        code = symbol["code"]
        source = files.get(code)
        if source is None:
            result.append({**symbol, "price": None, "date": None})
            issues.append({"code": code, "error": "CSV 없음 또는 동일 종목 CSV 중복"})
            continue
        stat = source.stat()
        signature = [str(source.resolve()), stat.st_size, stat.st_mtime_ns]
        cached = old_manifest.get(code, {})
        history_path = history_dir / f"{code}.js"
        if cached.get("signature") == signature and history_path.is_file():
            item = {**cached["summary"], **symbol}
        else:
            try:
                points, metadata = read_prices(source)
                item = summary(symbol, points, metadata)
                metadata["source"] = "기존 프로젝트 raw/daily CSV (FinanceDataReader)"
                write_history(history_path, code, points, metadata)
            except (ValueError, OSError, csv.Error) as exc:
                result.append({**symbol, "price": None, "date": None})
                issues.append({"code": code, "error": str(exc)})
                continue
        manifest[code] = {"signature": signature, "summary": item}
        result.append(item)
    payload = {"version": 1, "generated_at": now_text(), "symbols": result,
               "counts": dict(Counter(row["market"] for row in result)),
               "cached_count": sum(row.get("price") is not None for row in result),
               "issues": issues, "notice": "저장 시세이며 실시간 가격을 보장하지 않습니다."}
    atomic_text(manifest_path, dumps(manifest))
    atomic_text(target / "market.json", dumps(payload))
    template = (ROOT / "portfolio_dashboard.template.html").read_text(encoding="utf-8")
    atomic_text(output_dir / "portfolio_dashboard.html", template.replace("/*__KRX_DATA__*/null", script_json(payload)))
    print(dumps({"html": str(output_dir / "portfolio_dashboard.html"), "symbols": len(result),
                 "cached": payload["cached_count"], "issues": len(issues)}), flush=True)
    return payload


def fetch_child(code, start):
    import FinanceDataReader as fdr
    # Reuse normalization from the user's project; do not run its batch updater.
    from data_store import clean_fdr_ohlcv
    frame = clean_fdr_ohlcv(fdr.DataReader(code, start, datetime.now(KST).date().isoformat()))
    points = [[row.date.strftime("%Y-%m-%d"), numeric(row.close), numeric(row.volume)]
              for row in frame.itertuples() if numeric(row.close) is not None and row.close > 0]
    if not points:
        raise ValueError("온라인 조회에서 유효한 가격을 받지 못했습니다.")
    print(dumps({"points": points}), flush=True)


def refresh_symbol(code, output_dir=ROOT):
    target = output_dir / "portfolio_dashboard_data"
    payload = json.loads((target / "market.json").read_text(encoding="utf-8"))
    symbol = next((item for item in payload["symbols"] if item["code"] == code), None)
    if symbol is None or not CODE.fullmatch(code):
        raise ValueError("종목 마스터에서 확인할 수 없는 코드입니다.")
    start = symbol.get("meta", {}).get("first_date") or (date.today() - timedelta(days=365 * 3)).isoformat()
    completed = subprocess.run([sys.executable, "-B", str(ROOT / "portfolio_dashboard.py"),
                                "--fetch-child", code, "--start", start],
                               cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=50)
    if completed.returncode:
        raise RuntimeError("FDR 온라인 조회 실패. 기존 저장 시세를 유지합니다. " + completed.stderr[-220:])
    points = json.loads(completed.stdout.strip().splitlines()[-1])["points"]
    metadata = {"first_date": points[0][0], "last_date": points[-1][0], "rows": len(points),
                "source": "FinanceDataReader 온라인 조회 (기존 clean_fdr_ohlcv 적용)",
                "source_asof": now_text(), "source_status": "장중/확정 종가 여부 미검증",
                "price_basis": "FDR 조회 가격 · 조정 기준 미확인"}
    updated = summary(symbol, points, metadata)
    write_history(target / "history" / f"{code}.js", code, points, metadata)
    payload["symbols"] = [updated if item["code"] == code else item for item in payload["symbols"]]
    payload["generated_at"] = now_text()
    payload["cached_count"] = sum(item.get("price") is not None for item in payload["symbols"])
    # Invalidate the export cache for this symbol so later CSV export is explicit.
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop(code, None)
    atomic_text(manifest_path, dumps(manifest))
    atomic_text(target / "market.json", dumps(payload))
    template = (ROOT / "portfolio_dashboard.template.html").read_text(encoding="utf-8")
    atomic_text(output_dir / "portfolio_dashboard.html", template.replace("/*__KRX_DATA__*/null", script_json(payload)))
    return updated


def serve(port):
    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, payload):
            raw = dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
                return self.respond(403, {"error": "로컬 접속만 허용됩니다."})
            path = urlparse(self.path).path
            if path == "/api/status":
                return self.respond(200, {"online_refresh": True})
            if path in {"/", "/portfolio_dashboard.html"}:
                file = ROOT / "portfolio_dashboard.html"
                mime = "text/html; charset=utf-8"
            elif re.fullmatch(r"/portfolio_dashboard_data/history/[0-9A-Za-z]{6}\.js", path):
                file = ROOT / path.lstrip("/")
                mime = "text/javascript; charset=utf-8"
            else:
                return self.respond(404, {"error": "허용되지 않은 경로입니다."})
            if not file.is_file():
                return self.respond(404, {"error": "파일이 없습니다. HTML을 다시 생성하세요."})
            raw = file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            allowed = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
            if self.headers.get("Origin") not in allowed or self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
                return self.respond(403, {"error": "동일 로컬 화면에서만 갱신할 수 있습니다."})
            if urlparse(self.path).path != "/api/refresh":
                return self.respond(404, {"error": "경로 없음"})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.respond(415, {"error": "JSON 요청만 허용됩니다."})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 1024:
                    return self.respond(400, {"error": "잘못된 요청 크기"})
                request = json.loads(self.rfile.read(size))
                code = str(request.get("code", ""))
                if not CODE.fullmatch(code):
                    return self.respond(400, {"error": "잘못된 종목코드"})
                if not BUILD_LOCK.acquire(blocking=False):
                    return self.respond(409, {"error": "다른 종목을 갱신 중입니다."})
                try:
                    item = refresh_symbol(code)
                finally:
                    BUILD_LOCK.release()
                self.respond(200, {"symbol": item})
            except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
                self.respond(502, {"error": str(exc)[:350]})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Local: http://127.0.0.1:{port}/portfolio_dashboard.html", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description="KRX CSV를 연결한 로컬 HTML 포트폴리오")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT)
    parser.add_argument("--serve", action="store_true", help="HTML 생성 후 로컬 서버 실행")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--fetch-child", help=argparse.SUPPRESS)
    parser.add_argument("--start", default="2023-01-01", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.fetch_child:
        if not CODE.fullmatch(args.fetch_child):
            parser.error("잘못된 코드")
        fetch_child(args.fetch_child, args.start)
        return
    if args.serve and args.output_dir.resolve() != ROOT.resolve():
        parser.error("--serve는 기본 프로젝트 출력 위치에서만 사용할 수 있습니다.")
    export_dashboard(args.data_dir, args.output_dir)
    if args.serve:
        serve(args.port)


if __name__ == "__main__":
    main()
