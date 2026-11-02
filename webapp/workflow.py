from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

DONE = "done"
TODO = "todo"
WAITING = "waiting"


def latest_weekday(today: date) -> date:
    """오늘 또는 직전 평일. 공휴일은 구분하지 않는다."""
    return today - timedelta(days=max(today.weekday() - 4, 0))


def _parse_scan_time(label: object) -> Optional[datetime]:
    try:
        return datetime.strptime(str(label), "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def _parse_collection_time(text: object) -> Optional[datetime]:
    try:
        return datetime.strptime(str(text), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def market_trade_dates(data_status: dict) -> dict[str, str]:
    """데이터가 있는 시장별 최신 일자."""
    markets = data_status.get("markets") or {}
    return {
        name: str(stat["latest_trade_date"])
        for name, stat in markets.items()
        if stat.get("latest_trade_date")
    }


def mismatched_market_message(data_status: dict) -> Optional[str]:
    """시장별 최신 일자가 다르면 경고 문구를 돌려준다."""
    dates = market_trade_dates(data_status)
    if len(set(dates.values())) <= 1:
        return None
    detail = ", ".join(f"{name} {value}" for name, value in dates.items())
    return f"시장별 데이터 기준일이 다릅니다 ({detail}). 스캔 전에 전체 업데이트를 권장합니다."


def build_steps(data_status: dict, scan_status: dict, today: date) -> list[dict]:
    """데이터 저장 → 돌파 서칭 → 결과 조회의 현재 상태를 계산한다."""
    # 일부 시장만 갱신한 경우 가장 뒤처진 시장을 기준으로 판단한다.
    trade_date = min(market_trade_dates(data_status).values(), default=data_status.get("latest_trade_date"))
    data_done = bool(trade_date) and str(trade_date) >= latest_weekday(today).strftime("%Y-%m-%d")

    scan_time = _parse_scan_time(scan_status.get("latest_scan_label"))
    collected_at = _parse_collection_time(data_status.get("latest_collection_date"))
    scan_done = scan_time is not None and (collected_at is None or scan_time >= collected_at)

    if not data_done:
        scan_state = WAITING
    else:
        scan_state = DONE if scan_done else TODO

    return [
        {
            "title": "데이터 저장",
            "state": DONE if data_done else TODO,
            "detail": f"최신 {trade_date}" if trade_date else "데이터 없음",
            "menu": 1,
        },
        {
            "title": "돌파 서칭",
            "state": scan_state,
            "detail": (
                scan_time.strftime("%m-%d %H:%M 스캔") if scan_time is not None else "스캔 결과 없음"
            ) if scan_done else "최신 데이터 기준 스캔 필요",
            "menu": 2,
        },
        {
            "title": "결과 조회",
            "state": DONE if scan_state == DONE else WAITING,
            "detail": (
                f"돌파 {int(scan_status.get('total_breakouts', 0)):,}건"
                if scan_state == DONE
                else "스캔 후 확인 가능"
            ),
            "menu": 3,
        },
    ]
