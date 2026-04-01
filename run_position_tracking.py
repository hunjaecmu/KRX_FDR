from __future__ import annotations

from position_tracker import run_position_tracking


def main() -> None:
    result = run_position_tracking()

    if result.get("status") == "ok":
        print("[TRACKING] 생성 완료")
        print(f"rows={result.get('rows')}")
        print(f"snapshot_file={result.get('snapshot_file')}")
        print(f"history_file={result.get('history_file')}")
    else:
        print("[TRACKING][WARN] 생성 생략")
        print(f"status={result.get('status')}")
        print(f"message={result.get('message')}")
        print(f"holdings_csv={result.get('holdings_csv')}")


if __name__ == "__main__":
    main()
