import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import import_icloud_data as importer


def frame(dates, closes, status="종가", volume=100):
    return pd.DataFrame({
        "date": pd.to_datetime(dates),
        "open": closes, "high": closes, "low": closes, "close": closes,
        "volume": [volume] * len(dates),
        "asof_datetime": "", "asof_date": "", "asof_time": "",
        "price_status": [status] * len(dates),
    })


class MergeRawTests(unittest.TestCase):
    def test_keeps_older_local_history_and_takes_mac_values(self):
        local = frame(["2026-01-02", "2026-01-05", "2026-01-06"], [100.0, 101.0, 102.0])
        incoming = frame(["2026-01-05", "2026-01-06", "2026-01-07"], [101.0, 102.5, 103.0])
        merged, how = importer.merge_raw(local, incoming)
        self.assertEqual(how, "merged")
        self.assertEqual(merged["close"].tolist(), [100.0, 101.0, 102.5, 103.0])

    def test_same_data_is_not_rewritten(self):
        local = frame(["2026-01-05", "2026-01-06"], [101.0, 102.0])
        merged, how = importer.merge_raw(local, local.copy())
        self.assertEqual(how, "same")

    def test_intraday_to_final_counts_as_change(self):
        local = frame(["2026-01-05", "2026-01-06"], [101.0, 102.0], status="장중")
        incoming = frame(["2026-01-05", "2026-01-06"], [101.0, 102.0])
        self.assertEqual(importer.merge_raw(local, incoming)[1], "merged")

    def test_adjusted_prices_replace_whole_history(self):
        local = frame(["2026-01-02", "2026-01-05", "2026-01-06"], [1000.0, 1010.0, 1020.0])
        incoming = frame(["2026-01-05", "2026-01-06"], [101.0, 102.0])
        merged, how = importer.merge_raw(local, incoming)
        self.assertEqual(how, "replaced")
        self.assertEqual(merged["close"].tolist(), [101.0, 102.0])

    def test_new_stock_takes_mac_file(self):
        incoming = frame(["2026-01-05"], [101.0])
        merged, how = importer.merge_raw(frame([], []), incoming)
        self.assertEqual(how, "new")


if __name__ == "__main__":
    unittest.main()
