# scripts/scan_market.py

from market_scanner import (
    scan_all_breakouts,
    print_scan_results,
    save_scan_results_to_csv
)

from chart_viewer import show_breakout_charts


def main():

    results = scan_all_breakouts()

    print_scan_results(results)

    folder = save_scan_results_to_csv(results)

    show_breakout_charts(results, save_root=folder)


if __name__ == "__main__":
    main()