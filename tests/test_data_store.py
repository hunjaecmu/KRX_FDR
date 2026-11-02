import os
import sys
import tempfile
import unittest
from unittest import mock

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data_store as ds


RAW_COLUMNS = [
    "date", "open", "high", "low", "close", "volume",
    "asof_datetime", "asof_date", "asof_time", "price_status",
]


def raw_rows(dates_status: list[tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "date": d, "open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000,
            "asof_datetime": f"{d} 16:00:00", "asof_date": d, "asof_time": "16:00", "price_status": s,
        }
        for d, s in dates_status
    ], columns=RAW_COLUMNS)


def fetched(dates: list[str], close: int = 200) -> pd.DataFrame:
    df = raw_rows([(d, "종가") for d in dates])
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = close
    return df


class UpdateOneRawStockTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        patcher = mock.patch.object(ds, "RAW_DAILY_DIR", temp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        today = mock.patch.object(ds, "today_str", return_value="2026-11-03")
        today.start()
        self.addCleanup(today.stop)
        self.path = ds.raw_file_path("005930", "삼성전자")

    def save(self, rows):
        raw_rows(rows).to_csv(self.path, index=False, encoding="utf-8-sig")

    def run_update(self, fetch_result=None):
        fetch = mock.Mock(return_value=fetch_result if fetch_result is not None else fetched([]))
        with mock.patch.object(ds, "fetch_ohlcv_with_retry", fetch):
            return ds.update_one_raw_stock("005930", "삼성전자", save=False), fetch

    def test_skip_when_today_is_final(self):
        self.save([("2026-11-02", "종가"), ("2026-11-03", "종가")])
        res, fetch = self.run_update()
        self.assertEqual(res["status"], "skip")
        fetch.assert_not_called()

    def test_incremental_starts_after_last_saved(self):
        self.save([("2026-11-02", "종가")])
        res, fetch = self.run_update(fetched(["2026-11-03"]))
        self.assertEqual(res["status"], "incr")
        self.assertEqual(fetch.call_args.args[1], "2026-11-03")
        self.assertEqual(len(res["_pending_data"]), 2)

    def test_same_day_intraday_is_refetched(self):
        self.save([("2026-11-02", "종가"), ("2026-11-03", "장중")])
        res, fetch = self.run_update(fetched(["2026-11-03"]))
        self.assertEqual(fetch.call_args.args[1], "2026-11-03")
        merged = res["_pending_data"]
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged.iloc[-1]["price_status"], "종가")

    def test_past_intraday_is_repaired_and_kept_in_merge(self):
        self.save([("2026-10-30", "종가"), ("2026-11-02", "장중")])
        fetch = mock.Mock(side_effect=[fetched(["2026-11-02"], close=300), fetched(["2026-11-03"], close=400)])
        with mock.patch.object(ds, "fetch_ohlcv_with_retry", fetch):
            res = ds.update_one_raw_stock("005930", "삼성전자", save=False)
        merged = res["_pending_data"].set_index(res["_pending_data"]["date"].dt.strftime("%Y-%m-%d"))
        self.assertEqual(merged.loc["2026-11-02", "close"], 300)
        self.assertEqual(merged.loc["2026-11-02", "price_status"], "종가")
        self.assertEqual(merged.loc["2026-11-03", "close"], 400)

    def test_missing_file_fetches_from_initial_date(self):
        res, fetch = self.run_update(fetched(["2026-11-03"]))
        self.assertEqual(res["status"], "init")
        self.assertEqual(fetch.call_args.args[1], ds.initial_start_date())

    def test_no_new_data_keeps_file_untouched(self):
        self.save([("2026-11-02", "종가")])
        res, _ = self.run_update(fetched([]))
        self.assertEqual(res["status"], "empty")
        self.assertFalse(res["updated"])

    def test_existing_file_is_read_once(self):
        self.save([("2026-11-02", "종가")])
        with mock.patch.object(ds, "load_raw_daily", wraps=ds.load_raw_daily) as load:
            self.run_update(fetched(["2026-11-03"]))
        self.assertEqual(load.call_count, 1)

    def test_unreadable_dates_fail_without_fetching(self):
        with open(self.path, "w", encoding="utf-8-sig") as f:
            f.write("date,open,high,low,close,volume\nnot-a-date,1,1,1,1,1\n")
        res, fetch = self.run_update()
        self.assertEqual(res["status"], "fail")
        fetch.assert_not_called()


class UpdateIndicesTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = temp.name
        for patcher in (
            mock.patch.object(ds, "INDEX_WEEKLY_DIR", self.dir),
            mock.patch.object(ds, "ensure_dirs"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_saves_weekly_files(self):
        with mock.patch.object(ds, "fetch_ohlcv_with_retry", return_value=fetched(["2026-11-02", "2026-11-03"])):
            ds.update_indices()
        self.assertEqual(sorted(os.listdir(self.dir)), ["KQ11_KOSDAQ.csv", "KS11_KOSPI.csv"])

    def test_failure_keeps_existing_file_and_continues(self):
        existing = os.path.join(self.dir, "KS11_KOSPI.csv")
        with open(existing, "w", encoding="utf-8") as f:
            f.write("old")
        fetch = mock.Mock(side_effect=[RuntimeError("down"), fetched(["2026-11-02"])])
        with mock.patch.object(ds, "fetch_ohlcv_with_retry", fetch):
            ds.update_indices()
        with open(existing, encoding="utf-8") as f:
            self.assertEqual(f.read(), "old")
        self.assertTrue(os.path.exists(os.path.join(self.dir, "KQ11_KOSDAQ.csv")))


class GenerateDerivedAllTests(unittest.TestCase):
    def test_parallel_failure_of_pool_falls_back_to_sequential(self):
        from concurrent.futures.process import BrokenProcessPool

        tasks = [("000001", "A"), ("000002", "B")]
        with mock.patch.object(ds, "ProcessPoolExecutor", side_effect=BrokenProcessPool("boom")), \
                mock.patch.object(ds, "generate_derived_for_one_stock", return_value={"status": "ok"}) as gen:
            res = ds.generate_derived_all(tasks, total=2, max_workers=4)
        self.assertEqual(set(res), {"000001", "000002"})
        self.assertEqual(gen.call_count, 2)


if __name__ == "__main__":
    unittest.main()
