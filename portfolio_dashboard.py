"""Local HTML portfolio that fetches its own prices with FinanceDataReader.

It does not read the KRX_FDR scan data. The stock list comes from FDR listings
(refreshed once a day) and daily prices are fetched only for held codes.
Generated files live alongside the HTML in portfolio_dashboard_data/.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import threading
import hashlib
import socket
import time
import urllib.request
import webbrowser
import portfolio_personal_storage as personal_storage
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent
CODE = re.compile(r"[0-9A-Za-z]{6}\Z")
BUILD_LOCK = threading.Lock()
JOB_LOCK = threading.Lock()
UPDATE_JOB = {"state": "idle", "done": 0, "total": 0}
# 보유 종목을 처음 받을 때의 시작일. 이후에는 마지막 날짜 근처부터 이어 받는다.
PRICE_START = "2014-01-01"
REFETCH_DAYS = 10
FETCH_TIMEOUT = 50
FETCH_TIMEOUT_PER_CODE = 10
INSTANCE_ID = hashlib.sha256(str(ROOT.resolve()).encode("utf-8")).hexdigest()[:16]


def now_text():
    return datetime.now(KST).isoformat(timespec="seconds")


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


def symbol_row(code, name, market):
    market = str(market).strip().upper()
    is_etf = market in {"ETF/KR", "ETF"}
    return {"code": code, "name": name or code,
            "market": "ETF" if is_etf else "KOSDAQ" if market.startswith("KOSDAQ") else market,
            "market_detail": market, "currency": "KRW",
            "instrument_type": "ETF" if is_etf else "stock"}


def run_child(*args, timeout=FETCH_TIMEOUT):
    """FDR 조회는 멈출 수 있어 별도 프로세스에서 시간 제한을 두고 실행한다."""
    completed = subprocess.run([sys.executable, "-B", str(ROOT / "portfolio_dashboard.py"), *args],
                               cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=timeout)
    if completed.returncode:
        raise RuntimeError("FDR 온라인 조회 실패. " + completed.stderr[-220:])
    return json.loads(completed.stdout.strip().splitlines()[-1])


def fetch_listing_child():
    import FinanceDataReader as fdr
    rows = []
    for row in fdr.StockListing("KRX").itertuples():
        market = str(row.Market).strip().upper()
        if market == "KOSPI" or market.startswith("KOSDAQ"):
            rows.append([str(row.Code).strip(), str(row.Name).strip(), market])
    for row in fdr.StockListing("ETF/KR").itertuples():
        rows.append([str(row.Symbol).strip(), str(row.Name).strip(), "ETF/KR"])
    rows = [row for row in rows if CODE.fullmatch(row[0])]
    if not rows:
        raise ValueError("종목 목록이 비어 있습니다.")
    print(dumps({"rows": rows}), flush=True)


def load_symbols(target):
    """FDR 종목 목록을 하루 한 번 받는다. 실패하면 지난번 목록을 쓴다."""
    path = target / "symbols.json"
    cached = {}
    if path.is_file():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            cached = {}
    issue = None
    if cached.get("fetched_on") != date.today().isoformat():
        try:
            cached = {"fetched_on": date.today().isoformat(), "rows": run_child("--fetch-listing")["rows"]}
            atomic_text(path, dumps(cached))
        except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
            issue = {"code": "LISTING", "error": "종목 목록 갱신 실패, 지난 목록 사용: " + str(exc)[-200:]}
    symbols = {code: symbol_row(code, name, market) for code, name, market in cached.get("rows", [])}
    return symbols, issue


def holding_codes():
    try:
        doc = read_portfolio_file()["document"]
    except (ValueError, OSError):
        return {}
    codes = {}
    for holding in (doc or {}).get("holdings", []):
        code = str(holding.get("code", "")).upper()
        if holding.get("currency") == "KRW" and CODE.fullmatch(code):
            codes.setdefault(code, holding.get("name") or code)
    return codes


def price_cache_path(target, code):
    return target / "prices" / f"{code}.json"


def read_price_cache(target, code):
    path = price_cache_path(target, code)
    if not path.is_file():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))["points"]
    except (ValueError, OSError, KeyError):
        return []


def price_metadata(points):
    last = points[-1][0]
    # 장 마감(15:30) 전에 받은 오늘 가격은 장중 값이다.
    now = datetime.now(KST)
    status = "장중" if last == now.date().isoformat() and now.strftime("%H:%M") < "15:40" else "종가"
    return {"first_date": points[0][0], "last_date": last, "rows": len(points),
            "source": "FinanceDataReader 온라인 조회", "source_asof": now_text(), "source_status": status,
            "price_basis": "FDR 조회 가격"}


def update_prices(target, codes):
    """종목들의 일별 가격을 이어 받아 저장한다. ({코드: (points, metadata)}, {코드: 오류})를 돌려준다."""
    cached = {code: read_price_cache(target, code) for code in codes}
    requests = []
    for code, points in cached.items():
        start = PRICE_START
        if points:
            start = (date.fromisoformat(points[-1][0]) - timedelta(days=REFETCH_DAYS)).isoformat()
        requests.append(f"{code}:{start}")
    # 프로세스를 띄우는 비용이 커서 한 번에 받는다.
    fetched = run_child("--fetch-child", ",".join(requests),
                        timeout=FETCH_TIMEOUT + FETCH_TIMEOUT_PER_CODE * len(requests))
    updated = {}
    for code, rows in fetched["points"].items():
        merged = {row[0]: row for row in cached.get(code, [])}
        merged.update({row[0]: row for row in rows})
        points = [merged[day] for day in sorted(merged)]
        atomic_text(price_cache_path(target, code), dumps({"code": code, "points": points}))
        updated[code] = (points, price_metadata(points))
    return updated, fetched["errors"]


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


def export_dashboard(output_dir=ROOT, progress=None):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_dir.resolve() != ROOT.resolve():
        atomic_text(output_dir / "portfolio_accounts.js", (ROOT / "portfolio_accounts.js").read_text(encoding="utf-8"))
        atomic_text(output_dir / "portfolio_storage.js", (ROOT / "portfolio_storage.js").read_text(encoding="utf-8"))
        atomic_text(output_dir / "portfolio_asset_management.js", (ROOT / "portfolio_asset_management.js").read_text(encoding="utf-8"))
    target = output_dir / "portfolio_dashboard_data"
    history_dir = target / "history"
    symbols, listing_issue = load_symbols(target)
    issues = [listing_issue] if listing_issue else []
    holdings = holding_codes()
    for code, name in holdings.items():
        symbols.setdefault(code, symbol_row(code, name, "ETF" if not code.isdigit() else "미확인"))
    # 보유 종목만 온라인으로 받고, 나머지는 이전에 받아 둔 가격이 있으면 그대로 보여준다.
    if progress:
        progress(0, len(holdings))
    try:
        updated, errors = update_prices(target, sorted(holdings)) if holdings else ({}, {})
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
        updated, errors = {}, {code: str(exc)[-200:] for code in holdings}
    for code, (points, metadata) in updated.items():
        write_history(history_dir / f"{code}.js", code, points, metadata)
    # KRX_FDR CSV로 만들던 예전 차트 파일은 받아 둔 가격이 없으면 지운다.
    (target / "manifest.json").unlink(missing_ok=True)
    for stale in history_dir.glob("*.js"):
        if not price_cache_path(target, stale.stem).is_file():
            stale.unlink()
    issues += [{"code": code, "error": "가격 갱신 실패, 지난 가격 유지: " + error} for code, error in errors.items()]
    result = []
    for code in sorted(symbols):
        points = read_price_cache(target, code)
        if points:
            result.append(summary(symbols[code], points, price_metadata(points)))
        else:
            result.append({**symbols[code], "price": None, "date": None})
    payload = {"version": 1, "generated_at": now_text(), "symbols": result,
               "counts": dict(Counter(row["market"] for row in result)),
               "cached_count": sum(row.get("price") is not None for row in result),
               "holding_count": len(holdings),
               "issues": issues, "notice": "보유 종목만 FinanceDataReader로 갱신하며 실시간 가격을 보장하지 않습니다."}
    atomic_text(target / "market.json", dumps(payload))
    template = (ROOT / "portfolio_dashboard.template.html").read_text(encoding="utf-8")
    atomic_text(output_dir / "portfolio_dashboard.html", template.replace("/*__KRX_DATA__*/null", script_json(payload)).replace("/*__KRX_LAUNCHER__*/null", script_json(launcher_text())).replace('/*__KRX_LAUNCHER_NAME__*/"portfolio_dashboard_start.cmd"', script_json(LAUNCHER_NAME)).replace("/*__PERSONAL_STORAGE_CONFIG__*/null", script_json(personal_storage.public_config(ROOT))).replace("/*__PORTFOLIO_STORAGE__*/", (ROOT / "portfolio_storage.js").read_text(encoding="utf-8").replace("</script", "<\\/script")))
    if progress:
        progress(len(holdings), len(holdings))
    print(dumps({"html": str(output_dir / "portfolio_dashboard.html"), "symbols": len(result),
                 "cached": payload["cached_count"], "issues": len(issues)}), flush=True)
    return payload


def render_existing(output_dir=ROOT):
    output_dir = Path(output_dir)
    if output_dir.resolve() != ROOT.resolve():
        atomic_text(output_dir / "portfolio_accounts.js", (ROOT / "portfolio_accounts.js").read_text(encoding="utf-8"))
        atomic_text(output_dir / "portfolio_storage.js", (ROOT / "portfolio_storage.js").read_text(encoding="utf-8"))
        atomic_text(output_dir / "portfolio_asset_management.js", (ROOT / "portfolio_asset_management.js").read_text(encoding="utf-8"))
    payload = json.loads((output_dir / "portfolio_dashboard_data" / "market.json").read_text(encoding="utf-8"))
    template = (ROOT / "portfolio_dashboard.template.html").read_text(encoding="utf-8")
    atomic_text(output_dir / "portfolio_dashboard.html", template.replace("/*__KRX_DATA__*/null", script_json(payload)).replace("/*__KRX_LAUNCHER__*/null", script_json(launcher_text())).replace('/*__KRX_LAUNCHER_NAME__*/"portfolio_dashboard_start.cmd"', script_json(LAUNCHER_NAME)).replace("/*__PERSONAL_STORAGE_CONFIG__*/null", script_json(personal_storage.public_config(ROOT))).replace("/*__PORTFOLIO_STORAGE__*/", (ROOT / "portfolio_storage.js").read_text(encoding="utf-8").replace("</script", "<\\/script")))
    print(dumps({"html": str(output_dir / "portfolio_dashboard.html"), "mode": "render-existing", "symbols": len(payload["symbols"])}), flush=True)
    return payload


def fetch_child(requests):
    """"코드:시작일"을 쉼표로 이은 요청을 받아 종목별 가격과 오류를 JSON으로 출력한다."""
    import FinanceDataReader as fdr
    today = datetime.now(KST).date().isoformat()
    result, errors = {}, {}
    for request in requests.split(","):
        code, _, start = request.partition(":")
        try:
            if not CODE.fullmatch(code):
                raise ValueError("잘못된 코드")
            frame = fdr.DataReader(code, start or PRICE_START, today)
            points = [[day.strftime("%Y-%m-%d"), numeric(row["Close"]), numeric(row.get("Volume"))]
                      for day, row in frame.iterrows() if numeric(row["Close"]) is not None and row["Close"] > 0]
            if not points:
                raise ValueError("온라인 조회에서 유효한 가격을 받지 못했습니다.")
            result[code] = points
        except Exception as exc:
            errors[code] = str(exc)[:200]
    print(dumps({"points": result, "errors": errors}), flush=True)


def refresh_symbol(code, output_dir=ROOT):
    target = output_dir / "portfolio_dashboard_data"
    payload = json.loads((target / "market.json").read_text(encoding="utf-8"))
    symbol = next((item for item in payload["symbols"] if item["code"] == code), None)
    if symbol is None or not CODE.fullmatch(code):
        raise ValueError("종목 마스터에서 확인할 수 없는 코드입니다.")
    updated, errors = update_prices(target, [code])
    if code not in updated:
        raise RuntimeError("FDR 온라인 조회 실패. 기존 저장 시세를 유지합니다. " + errors.get(code, ""))
    points, metadata = updated[code]
    updated = summary(symbol, points, metadata)
    write_history(target / "history" / f"{code}.js", code, points, metadata)
    payload["symbols"] = [updated if item["code"] == code else item for item in payload["symbols"]]
    payload["generated_at"] = now_text()
    payload["cached_count"] = sum(item.get("price") is not None for item in payload["symbols"])
    atomic_text(target / "market.json", dumps(payload))
    template = (ROOT / "portfolio_dashboard.template.html").read_text(encoding="utf-8")
    atomic_text(output_dir / "portfolio_dashboard.html", template.replace("/*__KRX_DATA__*/null", script_json(payload)).replace("/*__KRX_LAUNCHER__*/null", script_json(launcher_text())).replace('/*__KRX_LAUNCHER_NAME__*/"portfolio_dashboard_start.cmd"', script_json(LAUNCHER_NAME)).replace("/*__PERSONAL_STORAGE_CONFIG__*/null", script_json(personal_storage.public_config(ROOT))).replace("/*__PORTFOLIO_STORAGE__*/", (ROOT / "portfolio_storage.js").read_text(encoding="utf-8").replace("</script", "<\\/script")))
    return updated


def job_status():
    with JOB_LOCK:
        return dict(UPDATE_JOB)


def start_market_update():
    if not BUILD_LOCK.acquire(blocking=False):
        return False
    with JOB_LOCK:
        UPDATE_JOB.clear()
        UPDATE_JOB.update(state="running", done=0, total=0, started_at=now_text())

    def progress(done, total):
        with JOB_LOCK:
            UPDATE_JOB.update(done=done, total=total)

    def work():
        try:
            payload = export_dashboard(progress=progress)
            with JOB_LOCK:
                UPDATE_JOB.update(state="complete", finished_at=now_text(),
                                  summary={"symbols": len(payload["symbols"]),
                                           "cached": payload["cached_count"], "issues": len(payload["issues"])})
        except Exception as exc:
            with JOB_LOCK:
                UPDATE_JOB.update(state="error", finished_at=now_text(), error=str(exc)[:350])
        finally:
            BUILD_LOCK.release()

    threading.Thread(target=work, daemon=True).start()
    return True


LAUNCHER_NAME = "portfolio_dashboard_start.cmd" if os.name == "nt" else "portfolio_dashboard_start.command"


def launcher_text():
    # A browser cannot execute Python. The downloaded fixed-purpose launcher invokes
    # only this script; it also works when saved outside the project directory.
    if os.name != "nt":
        import shlex
        return ('#!/bin/bash\n'
                + f'{shlex.quote(sys.executable)} -B {shlex.quote(str(ROOT / "portfolio_dashboard.py"))} --launch\n'
                + 'if [ $? -ne 0 ]; then\n echo "Unable to start KRX Portfolio. See the message above."\n'
                + ' read -n 1 -s -r -p "Press any key to close"\nfi\n')
    content = ('@echo off\r\nsetlocal\r\n'
               + f'"{sys.executable}" -B "{ROOT / "portfolio_dashboard.py"}" --launch\r\n'
               + 'if errorlevel 1 (\r\n echo Unable to start KRX Portfolio. See the message above.\r\n pause\r\n)\r\n')
    return content


def write_launcher():
    path = ROOT / LAUNCHER_NAME
    path.write_bytes(launcher_text().encode("utf-8"))
    if os.name != "nt":
        path.chmod(0o755)


def local_request(url, data=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    headers = {"Content-Type": "application/json"}
    if data is not None:
        parsed = urlparse(url)
        headers["Origin"] = f"{parsed.scheme}://{parsed.netloc}"
    req = urllib.request.Request(url, data=None if data is None else dumps(data).encode("utf-8"), headers=headers)
    with opener.open(req, timeout=1) as response:
        return json.loads(response.read())


def update_storage_server_url(port):
    path = ROOT / "portfolio_storage_config.json"
    if path.exists():
        config = json.loads(path.read_text(encoding="utf-8-sig"))
        config["server_url"] = f"http://127.0.0.1:{port}"
        atomic_text(path, personal_storage.json_text(config))


def launch_dashboard(port=8765, open_browser=True, personal=False):
    chosen = None
    spawned = False
    child = None
    for candidate in range(port, port + 10):
        base = f"http://127.0.0.1:{candidate}"
        try:
            info = local_request(base + "/api/status")
            if info.get("instance_id") == INSTANCE_ID and info.get("market_update") and info.get("portfolio_storage") and info.get("storage_layout") == 2 and info.get("asset_classification") == 1:
                chosen = candidate
                update_storage_server_url(chosen)
                render_existing(ROOT)
                break
        except Exception:
            pass
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", candidate))
            except OSError:
                continue
        chosen = candidate
        update_storage_server_url(chosen)
        log_path = ROOT / "portfolio_dashboard_data" / "server.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        with log_path.open("a", encoding="utf-8") as log:
            child = subprocess.Popen([sys.executable, "-B", str(ROOT / "portfolio_dashboard.py"),
                                      "--render-only", "--serve", "--port", str(chosen)],
                                     cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=env,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        spawned = True
        ready = False
        for _ in range(60):
            if child.poll() is not None:
                break
            try:
                ready = local_request(base + "/api/status").get("instance_id") == INSTANCE_ID
                if ready:
                    break
            except Exception:
                pass
            time.sleep(0.25)
        if not ready:
            if child.poll() is None:
                child.terminate()
            raise RuntimeError(f"서버를 시작하지 못했습니다. {log_path}를 확인하세요.")
        break
    if chosen is None:
        raise RuntimeError("사용 가능한 로컬 포트를 찾지 못했습니다.")
    base = f"http://127.0.0.1:{chosen}"
    if not personal:
        try:
            local_request(base + "/api/update-market", {})
        except Exception:
            pass
    url = base + ("/portfolio_dashboard.html?view=portfolio" if personal else "/portfolio_dashboard.html?view=market&update=1")
    if open_browser:
        webbrowser.open(url)
    return {"url": url, "spawned": spawned, "pid": child.pid if child else None}


PORTFOLIO_LOCK = threading.Lock()


def portfolio_path():
    return personal_storage.directories(ROOT)["main"] / "portfolio.json"


def validate_asset_classifications(doc):
    if "asset_classifications" not in doc:
        return
    records = doc["asset_classifications"]
    if not isinstance(records, dict) or len(records) > 20000:
        raise ValueError("공통 자산 분류 목록을 확인하세요.")
    for key, record in records.items():
        if not (isinstance(key, str) and re.fullmatch(r"(KRW|USD):[A-Z0-9][A-Z0-9.^:-]{0,23}", key) and isinstance(record, dict)):
            raise ValueError("공통 자산 분류 키를 확인하세요.")
        if not (record.get("region") in ("KR", "US", "GLOBAL", "OTHER", "UNKNOWN") and record.get("category") in ("broad_index", "thematic", "factor", "bond", "mixed", "individual", "cash_like", "other", "unknown") and record.get("management") in ("active", "passive", "unknown") and record.get("hedge") in ("hedged", "unhedged", "unknown") and record.get("status") in ("suggested", "confirmed")):
            raise ValueError("공통 자산 분류의 지역·유형·전략을 확인하세요.")
        tags = record.get("tags")
        if not isinstance(tags, list) or len(tags) > 3 or any(not isinstance(tag, str) or tag not in ("covered_call", "leverage", "inverse") for tag in tags) or len(set(tags)) != len(tags):
            raise ValueError("추가 운용전략을 확인하세요.")
        if not isinstance(record.get("theme"), str) or len(record["theme"]) > 100 or not isinstance(record.get("source"), str) or len(record["source"]) > 500:
            raise ValueError("분류 테마·근거를 확인하세요.")
        try:
            reviewed = record.get("reviewed_on")
            if "reviewed_on" not in record or reviewed is not None and (not isinstance(reviewed, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", reviewed)):
                raise ValueError()
            if reviewed is not None:
                date.fromisoformat(reviewed)
            if record["status"] == "confirmed" and reviewed is None:
                raise ValueError()
            if not isinstance(record.get("updated_at"), str) or len(record["updated_at"]) > 40:
                raise ValueError()
            datetime.fromisoformat(record["updated_at"].replace("Z", "+00:00"))
        except (TypeError, ValueError, OverflowError):
            raise ValueError("공통 자산 분류의 확인일을 확인하세요.") from None


def validate_dividend_receipts(doc):
    if "dividend_receipts" not in doc:
        return
    records = doc["dividend_receipts"]
    if not isinstance(records, list) or len(records) > 100000:
        raise ValueError("실제 배당 수령 기록 목록을 확인하세요.")
    ids = set()
    def text(value, maximum):
        return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("배당 수령 기록을 확인하세요.")
        amount, rate = record.get("amount"), record.get("usd_krw")
        if not (text(record.get("id"), 100) and record["id"] not in ids
                and text(record.get("account_id"), 100) and text(record.get("account_name"), 80)
                and text(record.get("name"), 100) and isinstance(record.get("code"), str)
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.^:-]{0,23}", record["code"])
                and record.get("currency") in ("KRW", "USD")
                and type(amount) in (int, float) and math.isfinite(amount) and 0 <= amount <= 1e15
                and "usd_krw" in record
                and (rate is None or type(rate) in (int, float) and math.isfinite(rate) and 0 < rate <= 1e7)
                and (record["currency"] != "KRW" or rate is None)
                and isinstance(record.get("memo"), str) and len(record["memo"]) <= 300):
            raise ValueError("배당 수령 기록의 계좌·종목·금액·환율을 확인하세요.")
        try:
            if not isinstance(record.get("received_on"), str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", record["received_on"]):
                raise ValueError()
            date.fromisoformat(record["received_on"])
            for key in ("created_at", "updated_at"):
                if not text(record.get(key), 40):
                    raise ValueError()
                datetime.fromisoformat(record[key].replace("Z", "+00:00"))
        except (ValueError, TypeError, OverflowError):
            raise ValueError("배당 수령 기록의 날짜를 확인하세요.") from None
        ids.add(record["id"])
    if "dividend_monthly_summary" in doc and (not isinstance(doc["dividend_monthly_summary"], list) or len(doc["dividend_monthly_summary"]) > 100000):
        raise ValueError("월별 배당 집계 목록을 확인하세요.")


def validate_saved_portfolio(doc):
    if not isinstance(doc, dict) or doc.get("schema_version") != 2:
        raise ValueError("문서 형식 v2가 필요합니다.")
    if not isinstance(doc.get("document_id"), str) or not doc["document_id"]:
        raise ValueError("문서 ID가 없습니다.")
    if type(doc.get("revision")) is not int or doc["revision"] < 0:
        raise ValueError("리비전이 올바르지 않습니다.")
    for key, limit in {"accounts": 1000, "holdings": 20000, "snapshots": 20000, "audit": 51000}.items():
        if not isinstance(doc.get(key), list) or len(doc[key]) > limit:
            raise ValueError(f"{key} 목록을 확인하세요.")
    ids = set()
    for account in doc["accounts"]:
        if not isinstance(account, dict) or not isinstance(account.get("id"), str) or account["id"] in ids or not isinstance(account.get("name"), str):
            raise ValueError("계좌 ID·이름을 확인하세요.")
        ids.add(account["id"])
    hids = set()
    for holding in doc["holdings"]:
        if not isinstance(holding, dict) or holding.get("account_id") not in ids or not isinstance(holding.get("id"), str) or holding["id"] in hids:
            raise ValueError("종목의 ID·계좌 연결을 확인하세요.")
        if "dividend" in holding:
            dividend = holding["dividend"]
            if not isinstance(dividend, dict) or not {"monthly_day", "amount_per_share"}.issubset(dividend):
                raise ValueError("예상 배당 정보가 올바르지 않습니다.")
            day = dividend.get("monthly_day")
            amount = dividend.get("amount_per_share")
            if day is not None and not (type(day) is int and 1 <= day <= 31):
                raise ValueError("배당일은 매월 1~31일입니다.")
            if amount is not None and not (type(amount) in (int, float) and math.isfinite(amount) and amount >= 0):
                raise ValueError("예상 배당액은 0 이상의 금액입니다.")
            if amount is not None and amount > 0 and day is None:
                raise ValueError("예상 배당액이 있으면 지급일을 입력하세요.")
        hids.add(holding["id"])
    if not isinstance(doc.get("fx"), dict):
        raise ValueError("환율 정보가 없습니다.")
    validate_dividend_receipts(doc)
    validate_asset_classifications(doc)
    dumps(doc)  # Reject nonfinite values before touching any file.
    return doc


def read_portfolio_file():
    path = portfolio_path()
    if not path.exists():
        return {"document": None, "version": None, "path": str(path), "paths": personal_storage.public_config(ROOT)}
    raw = path.read_bytes()
    doc = validate_saved_portfolio(json.loads(raw.decode("utf-8-sig")))
    return {"document": doc, "version": hashlib.sha256(raw).hexdigest(), "path": str(path), "paths": personal_storage.public_config(ROOT)}


def save_portfolio_file(request):
    doc = validate_saved_portfolio(request.get("document"))
    if "expected_version" not in request:
        raise ValueError("파일 버전이 필요합니다.")
    with PORTFOLIO_LOCK:
        current = read_portfolio_file()
        if request["expected_version"] != current["version"]:
            return 409, {"error": "다른 화면에서 파일이 변경됐습니다. 저장할 데이터를 선택하세요."}
        content = json.dumps(doc, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
        path = portfolio_path()
        previous = path.read_text(encoding="utf-8-sig") if current["document"] is not None else None
        personal_storage.write_bundle(ROOT, doc, content, previous_text=previous, writer=atomic_text)
        return 200, {"version": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "path": str(path), "paths": personal_storage.public_config(ROOT), "saved_at": now_text(), "revision": doc["revision"]}


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
            if path == "/api/storage-ping":
                raw = b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>'
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            if path == "/api/status":
                return self.respond(200, {"online_refresh": True, "market_update": True,
                                          "instance_id": INSTANCE_ID, "portfolio_storage": True, "storage_layout": 2, "asset_classification": 1, "storage_paths": personal_storage.public_config(ROOT)})
            if path == "/api/portfolio":
                try:
                    with PORTFOLIO_LOCK:
                        return self.respond(200, read_portfolio_file())
                except (ValueError, OSError) as exc:
                    return self.respond(500, {"error": "저장 파일을 읽지 못했습니다: " + str(exc)[:200]})
            if path == "/portfolio_storage.js":
                raw = (ROOT / "portfolio_storage.js").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/javascript; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return self.wfile.write(raw)
            if path == "/api/update-status":
                return self.respond(200, job_status())
            if path == "/api/market":
                try:
                    return self.respond(200, json.loads((ROOT / "portfolio_dashboard_data" / "market.json").read_text(encoding="utf-8")))
                except (ValueError, OSError) as exc:
                    return self.respond(500, {"error": str(exc)[:200]})
            if path in {"/portfolio_dashboard_start.cmd", "/portfolio_dashboard_start.command"}:
                file = ROOT / LAUNCHER_NAME
                if not file.exists():
                    write_launcher()
                raw = file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", f'attachment; filename="{LAUNCHER_NAME}"')
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                return self.wfile.write(raw)
            if path in {"/portfolio_accounts.js", "/portfolio_asset_management.js"}:
                file = ROOT / path.lstrip("/")
                mime = "text/javascript; charset=utf-8"
            elif path in {"/", "/portfolio_dashboard.html"}:
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
            request_path = urlparse(self.path).path
            if request_path not in {"/api/refresh", "/api/update-market", "/api/portfolio", "/api/export-file"}:
                return self.respond(404, {"error": "경로 없음"})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.respond(415, {"error": "JSON 요청만 허용됩니다."})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= (50 * 1024 * 1024 if request_path in {"/api/portfolio", "/api/export-file"} else 1024):
                    return self.respond(400, {"error": "잘못된 요청 크기"})
                request = json.loads(self.rfile.read(size))
                if not isinstance(request, dict):
                    return self.respond(400, {"error": "JSON 객체가 필요합니다."})
                if request_path == "/api/export-file":
                    try:
                        if str(request.get("name", "")).endswith(".json"):
                            validate_saved_portfolio(json.loads(request.get("content", "")))
                        with PORTFOLIO_LOCK:
                            exported = personal_storage.export_file(ROOT, request)
                        return self.respond(200, exported)
                    except (ValueError, TypeError) as exc:
                        return self.respond(400, {"error": str(exc)[:350]})
                if request_path == "/api/portfolio":
                    try:
                        status, result = save_portfolio_file(request)
                        return self.respond(status, result)
                    except ValueError as exc:
                        return self.respond(400, {"error": str(exc)[:350]})
                if request_path == "/api/update-market":
                    if not start_market_update():
                        return self.respond(409, {"error": "다른 업데이트가 진행 중입니다."})
                    return self.respond(202, job_status())
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
    parser = argparse.ArgumentParser(description="FinanceDataReader로 보유 종목 시세를 받는 로컬 HTML 포트폴리오")
    parser.add_argument("--output-dir", type=Path, default=ROOT)
    parser.add_argument("--render-only", action="store_true", help="기존 market.json으로 화면만 재생성")
    parser.add_argument("--serve", action="store_true", help="HTML 생성 후 로컬 서버 실행")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--launch", action="store_true", help="서버 시작·재사용 후 시장 화면 열기")
    parser.add_argument("--open-portfolio", action="store_true", help="개인 저장 화면 열기")
    parser.add_argument("--no-browser", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--fetch-child", help=argparse.SUPPRESS)
    parser.add_argument("--fetch-listing", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.fetch_child:
        fetch_child(args.fetch_child)
        return
    if args.fetch_listing:
        fetch_listing_child()
        return
    if args.launch:
        print(dumps(launch_dashboard(args.port, not args.no_browser, args.open_portfolio)), flush=True)
        return
    write_launcher()
    if args.serve and args.output_dir.resolve() != ROOT.resolve():
        parser.error("--serve는 기본 프로젝트 출력 위치에서만 사용할 수 있습니다.")
    if args.render_only:
        render_existing(args.output_dir)
    else:
        export_dashboard(args.output_dir)
    if args.serve:
        serve(args.port)


if __name__ == "__main__":
    main()
