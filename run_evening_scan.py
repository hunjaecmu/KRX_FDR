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
from chart_viewer import (
    show_breakout_charts,
    create_overview_image,
    create_scan_overview_html,
)
from position_tracker import run_position_tracking


def run_once():
    started_at = datetime.now()
    timestamp = started_at.strftime("%Y%m%d_%H%M%S")

    print("=" * 70)
    print(f"스캔 시작: {started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    try:
        html_sort_by = "strength"  # "strength" or "code"

        results = scan_all_breakouts()  # 필요하면 scan_all_breakouts(max_workers=8)

        print_scan_results(results)

        save_folder = save_scan_results_to_csv(results, timestamp=timestamp)
        print(f"\nCSV 저장 완료: {save_folder}")

        overview_path = create_overview_image(
            results,
            save_root=save_folder,
            min_pct=0.5,
            max_pct=5.0,
            show_first_page=False,
            pause_sec=0.0,
        )
        print(f"Overview 저장 완료: {overview_path}")

        tracking_result = run_position_tracking()
        if tracking_result.get("status") == "ok":
            print(
                "[TRACKING] 저장 완료 | "
                f"rows={tracking_result.get('rows')} | "
                f"snapshot={tracking_result.get('snapshot_file')} | "
                f"history={tracking_result.get('history_file')}"
            )
        else:
            print(
                "[TRACKING][WARN] 생성 생략 | "
                f"status={tracking_result.get('status')} | "
                f"message={tracking_result.get('message')}"
            )

        show_breakout_charts(results, save_root=save_folder)

        html_path = create_scan_overview_html(
            results,
            save_root=save_folder,
            timestamp=timestamp,
            sort_by=html_sort_by,
        )
        print(f"HTML 저장 완료: {html_path}")

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
    run_once()
    # run_daily_scheduler()