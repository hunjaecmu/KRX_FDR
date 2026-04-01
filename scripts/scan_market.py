# scripts/scan_market.py

import os
import sys

# Ensure project root is importable when this script is executed directly.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

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