# run_evening_scan.py

from __future__ import annotations

import time
from datetime import datetime, timedelta

from config import SCAN_HOUR, SCAN_MINUTE
from market_scanner import (
    scan_all_breakouts,
    print_scan_results,
    save_scan_results_to_csv,
)
from chart_viewer import show_breakout_charts


def run_once():
    started_at = datetime.now()
    timestamp = started_at.strftime("%Y%m%d_%H%M%S")

    print("=" * 70)
    print(f"스캔 시작: {started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    try:
        results = scan_all_breakouts()

        print_scan_results(results)

        save_folder = save_scan_results_to_csv(results, timestamp=timestamp)
        print(f"\nCSV 저장 완료: {save_folder}")

        show_breakout_charts(results, save_root=save_folder)

    except Exception as e:
        print(f"[RUN][FAIL] 스캔 실행 중 오류 발생: {e}")
        raise

    ended_at = datetime.now()
    elapsed = ended_at - started_at

    print("\n" + "=" * 70)
    print(f"스캔 종료: {ended_at.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"총 소요 시간: {elapsed}")
    print("=" * 70)


def seconds_until_target(hour: int, minute: int) -> float:
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if now >= target:
        target = target + timedelta(days=1)

    return (target - now).total_seconds()


def run_daily_scheduler():
    print(f"매일 {SCAN_HOUR:02d}:{SCAN_MINUTE:02d} 실행 대기 중")

    while True:
        try:
            wait_sec = seconds_until_target(SCAN_HOUR, SCAN_MINUTE)
            print(f"다음 실행까지 {wait_sec / 60:.1f}분 대기")
            time.sleep(wait_sec)

            run_once()

        except KeyboardInterrupt:
            print("\n[RUN] 사용자 중단")
            break

        except Exception as e:
            print(f"[RUN][WARN] 스케줄 실행 중 오류: {e}")
            print("[RUN] 60초 후 재대기")
            time.sleep(60)


if __name__ == "__main__":
    # 즉시 1회 실행
    run_once()

    # 매일 지정 시각 자동 실행
    # run_daily_scheduler()