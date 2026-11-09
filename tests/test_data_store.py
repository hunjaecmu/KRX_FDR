import json
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


class CollectOneStockTests(unittest.TestCase):
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

    def run_collect(self, *fetch_results):
        results = list(fetch_results) or [fetched([])]
        fetch = mock.Mock(side_effect=results)
        with mock.patch.object(ds, "fetch_ohlcv_with_retry", fetch):
            return ds.collect_one_stock("005930", "삼성전자"), fetch

    def test_skip_when_today_is_final(self):
        self.save([("2026-11-02", "종가"), ("2026-11-03", "종가")])
        res, fetch = self.run_collect()
        self.assertEqual(res["status"], "skip")
        fetch.assert_not_called()

    def test_incremental_starts_after_last_final_day(self):
        self.save([("2026-10-30", "종가"), ("2026-11-02", "종가")])
        res, fetch = self.run_collect(fetched(["2026-11-03"], close=105))
        self.assertEqual(res["status"], "incr")
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(fetch.call_args.args[1], "2026-11-03")
        delta = res["_delta"]
        self.assertEqual(list(delta["date"].dt.strftime("%Y-%m-%d")), ["2026-11-03"])
        self.assertEqual(delta["mode"].iloc[0], "incr")
        self.assertEqual(delta["code"].iloc[0], "005930")

    def test_same_day_intraday_is_refetched(self):
        self.save([("2026-11-02", "종가"), ("2026-11-03", "장중")])
        res, fetch = self.run_collect(fetched(["2026-11-03"], close=105))
        self.assertEqual(fetch.call_args.args[1], "2026-11-03")
        delta = res["_delta"]
        self.assertEqual(len(delta), 1)
        self.assertEqual(delta.iloc[-1]["price_status"], "종가")

    def test_past_intraday_rows_are_replaced_as_final(self):
        self.save([("2026-10-30", "종가"), ("2026-11-02", "장중")])
        new = fetched(["2026-11-02", "2026-11-03"], close=105)
        new["price_status"] = "장중"  # 수집 시각이 장중
        res, fetch = self.run_collect(new)
        self.assertEqual(fetch.call_args.args[1], "2026-10-31")
        delta = res["_delta"].set_index(res["_delta"]["date"].dt.strftime("%Y-%m-%d"))
        self.assertEqual(list(delta.index), ["2026-11-02", "2026-11-03"])
        self.assertEqual(delta.loc["2026-11-02", "price_status"], "종가")
        self.assertEqual(delta.loc["2026-11-03", "price_status"], "장중")

    def test_missing_file_fetches_from_initial_date(self):
        res, fetch = self.run_collect(fetched(["2026-11-03"]))
        self.assertEqual(res["status"], "init")
        self.assertEqual(fetch.call_args.args[1], ds.initial_start_date())
        self.assertEqual(res["_delta"]["mode"].iloc[0], "full")

    def test_no_new_data_keeps_file_untouched(self):
        self.save([("2026-11-02", "종가")])
        res, _ = self.run_collect(fetched([]))
        self.assertEqual(res["status"], "empty")
        self.assertFalse(res["updated"])

    def test_reads_only_the_tail_of_existing_file(self):
        self.save([("2026-11-02", "종가")])
        with mock.patch.object(ds, "load_raw_daily") as load:
            self.run_collect(fetched(["2026-11-03"]))
        load.assert_not_called()

    def test_tail_matches_full_load_for_long_file(self):
        dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2020-01-01", periods=600)]
        self.save([(d, "종가") for d in dates])
        tail = ds.load_raw_tail(self.path, rows=5)
        full = ds.load_raw_daily(self.path).tail(5).reset_index(drop=True)
        pd.testing.assert_frame_equal(tail, full)

    def test_unreadable_dates_fail_without_fetching(self):
        with open(self.path, "w", encoding="utf-8-sig") as f:
            f.write("date,open,high,low,close,volume\nnot-a-date,1,1,1,1,1\n")
        res, fetch = self.run_collect()
        self.assertEqual(res["status"], "fail")
        fetch.assert_not_called()


class DailyCloseFileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = temp.name
        self.raw_dir = os.path.join(self.dir, "raw")
        self.daily_dir = os.path.join(self.dir, "daily_close")
        os.makedirs(self.raw_dir)
        for patcher in (
            mock.patch.object(ds, "RAW_DAILY_DIR", self.raw_dir),
            mock.patch.object(ds, "DAILY_CLOSE_DIR", self.daily_dir),
            mock.patch.object(ds, "MASTER_FILE", os.path.join(self.dir, "none.csv")),
            mock.patch.object(ds, "INDEX_DIR", os.path.join(self.dir, "none")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def delta(self, code, name, mode, dates, close):
        df = fetched(dates, close=close)
        df.insert(0, "mode", mode)
        df.insert(0, "name", name)
        df.insert(0, "code", code)
        return df

    def test_write_chains_files_and_apply_merges(self):
        raw_rows([("2026-11-02", "종가")]).to_csv(ds.raw_file_path("000001", "A"), index=False, encoding="utf-8-sig")
        rows = pd.concat([
            self.delta("000001", "A", "incr", ["2026-11-03"], 200),
            self.delta("000002", "B", "full", ["2026-11-02", "2026-11-03"], 300),
        ], ignore_index=True)
        first = ds.write_daily_close(rows, failed=["000009"])
        second = ds.write_daily_close(rows.iloc[:1], failed=[])
        m1, m2 = ds.read_daily_close_manifest(first), ds.read_daily_close_manifest(second)
        self.assertIsNone(m1["prev"])
        self.assertEqual(m2["prev"], m1["id"])
        self.assertEqual(m1["failed"], ["000009"])
        self.assertEqual((m1["incr_stocks"], m1["full_stocks"]), (1, 1))

        res = ds.apply_daily_rows(ds.read_daily_close_rows(first))
        self.assertEqual({c: r["status"] for c, r in res.items()}, {"000001": "ok", "000002": "ok"})
        a = ds.load_raw_daily(ds.raw_file_path("000001", "A"))
        self.assertEqual(list(a["close"]), [105, 200])
        self.assertEqual(len(ds.load_raw_daily(ds.raw_file_path("000002", "B"))), 2)

        # 같은 파일을 다시 반영해도 결과는 같다.
        ds.apply_daily_rows(ds.read_daily_close_rows(first))
        self.assertEqual(len(ds.load_raw_daily(ds.raw_file_path("000001", "A"))), 2)

    def test_incremental_rows_without_base_file_are_not_applied(self):
        res = ds.apply_daily_rows(self.delta("000003", "C", "incr", ["2026-11-03"], 1))
        self.assertEqual(res["000003"]["status"], "missing_base")
        self.assertFalse(os.path.exists(ds.raw_file_path("000003", "C")))


class UpdateIndicesTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = temp.name
        self.weekly_dir = os.path.join(self.dir, "weekly")
        self.monthly_dir = os.path.join(self.dir, "monthly")
        os.makedirs(self.weekly_dir)
        os.makedirs(self.monthly_dir)
        for patcher in (
            mock.patch.object(ds, "INDEX_DIR", self.dir),
            mock.patch.object(ds, "INDEX_WEEKLY_DIR", self.weekly_dir),
            mock.patch.object(ds, "INDEX_MONTHLY_DIR", self.monthly_dir),
            mock.patch.object(ds, "ensure_dirs"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_saves_weekly_files(self):
        raw = fetched(["2026-11-02", "2026-11-03"])
        raw.loc[raw.index[0], "close"] = 100
        raw.loc[raw.index[1], "close"] = 102
        with mock.patch.object(ds, "fetch_ohlcv_with_retry", return_value=raw):
            ds.update_indices()
        self.assertEqual(sorted(os.listdir(self.weekly_dir)), ["KQ11_KOSDAQ.csv", "KS11_KOSPI.csv"])
        self.assertEqual(sorted(os.listdir(self.monthly_dir)), ["KQ11_KOSDAQ.csv", "KS11_KOSPI.csv"])
        with open(os.path.join(self.dir, "KS11_summary.json"), encoding="utf-8") as f:
            summary = json.load(f)
        self.assertEqual(summary["date"], "2026-11-03")
        self.assertEqual(summary["close"], 102)
        self.assertAlmostEqual(summary["change_pct"], 2.0)

    def test_past_day_is_final_even_when_collected_during_market_hours(self):
        raw = fetched(["2026-10-30", "2026-11-02"])
        raw["price_status"] = "장중"
        with mock.patch.object(ds, "today_str", return_value="2026-11-03"):
            self.assertEqual(ds.build_index_summary("KS11", "KOSPI", raw)["price_status"], "종가")
        with mock.patch.object(ds, "today_str", return_value="2026-11-02"):
            self.assertEqual(ds.build_index_summary("KS11", "KOSPI", raw)["price_status"], "장중")

    def test_summary_without_previous_day_has_no_change(self):
        summary = ds.build_index_summary("KS11", "KOSPI", fetched(["2026-11-03"]))
        self.assertIsNone(summary["change_pct"])

    def test_failure_keeps_existing_file_and_continues(self):
        existing = os.path.join(self.weekly_dir, "KS11_KOSPI.csv")
        with open(existing, "w", encoding="utf-8") as f:
            f.write("old")
        fetch = mock.Mock(side_effect=[RuntimeError("down"), fetched(["2026-11-02"])])
        with mock.patch.object(ds, "fetch_ohlcv_with_retry", fetch):
            ds.update_indices()
        with open(existing, encoding="utf-8") as f:
            self.assertEqual(f.read(), "old")
        self.assertTrue(os.path.exists(os.path.join(self.weekly_dir, "KQ11_KOSDAQ.csv")))


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
