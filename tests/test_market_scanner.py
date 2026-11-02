import os
import sys
import unittest
from datetime import datetime
from unittest import mock

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_scanner as ms


class MinCurrentBarDateTests(unittest.TestCase):
    def test_weekly_allows_this_and_previous_week(self):
        # 2026-11-02 is a Monday; this week's bar is dated Friday 11-06.
        self.assertEqual(ms.min_current_bar_date("weekly", datetime(2026, 11, 2)), pd.Timestamp("2026-10-30"))

    def test_weekly_on_weekend_uses_week_just_ended(self):
        self.assertEqual(ms.min_current_bar_date("weekly", datetime(2026, 11, 8)), pd.Timestamp("2026-10-30"))

    def test_monthly_allows_this_and_previous_month(self):
        self.assertEqual(ms.min_current_bar_date("monthly", datetime(2026, 11, 2)), pd.Timestamp("2026-10-31"))

    def test_monthly_across_year_boundary(self):
        self.assertEqual(ms.min_current_bar_date("monthly", datetime(2027, 1, 15)), pd.Timestamp("2026-12-31"))


class ScanOneStockTests(unittest.TestCase):
    def bars(self, dates: list[str]) -> pd.DataFrame:
        # Close crosses above a flat MA on the last traded bar, followed by zero-volume bars.
        n = len(dates)
        return pd.DataFrame({
            "date": pd.to_datetime(dates),
            "close": [90.0, 110.0] + [110.0] * (n - 2),
            "ma10": [100.0] * n,
            "ma240": [100.0] * n,
            "ma120": [100.0] * n,
            "ma180": [100.0] * n,
            "volume": [1000, 1000] + [0] * (n - 2),
            "is_final": [True] * n,
        })

    def scan(self, weekly: pd.DataFrame, monthly: pd.DataFrame) -> list[dict]:
        with mock.patch.object(ms, "load_weekly", return_value=weekly), \
                mock.patch.object(ms, "load_monthly", return_value=monthly), \
                mock.patch.object(ms, "min_current_bar_date", side_effect=lambda tf: pd.Timestamp(
                    "2026-10-30" if tf == "weekly" else "2026-10-31")):
            return ms._scan_one_stock(("000001", "테스트"))

    def test_old_breakout_of_halted_stock_is_excluded(self):
        weekly = self.bars(["2026-01-30", "2026-02-06", "2026-10-30", "2026-11-06"])
        monthly = self.bars(["2026-03-31", "2026-04-30", "2026-10-31", "2026-11-30"])
        self.assertEqual(self.scan(weekly, monthly), [])

    def test_breakout_on_current_or_previous_bar_is_kept(self):
        weekly = self.bars(["2026-10-23", "2026-10-30"])
        monthly = self.bars(["2026-10-31", "2026-11-30"])
        cases = {row["timeframe"] for row in self.scan(weekly, monthly)}
        self.assertEqual(cases, {"weekly", "monthly"})


if __name__ == "__main__":
    unittest.main()
