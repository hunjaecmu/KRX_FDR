import os
import sys
import tempfile
import unittest
from unittest import mock

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import data_store as ds  # noqa: E402
import share_full_data as share  # noqa: E402


def chain(*pairs):
    return [(i, p, f"/x/{i}.zip") for i, p in pairs]


class PendingAfterTests(unittest.TestCase):
    def test_returns_files_after_last_applied(self):
        c = chain(("a1", None), ("a2", "a1"), ("a3", "a2"))
        self.assertEqual([x[0] for x in share._pending_after(c, "a1")], ["a2", "a3"])
        self.assertEqual(share._pending_after(c, "a3"), [])

    def test_gap_needs_full_bundle(self):
        c = chain(("a1", None), ("a3", "a2"))
        self.assertIsNone(share._pending_after(c, "a1"))

    def test_pruned_last_applied_still_links(self):
        c = chain(("a2", "a1"), ("a3", "a2"))
        self.assertEqual([x[0] for x in share._pending_after(c, "a1")], ["a2", "a3"])
        self.assertIsNone(share._pending_after(c, "a0"))

    def test_no_state_needs_full_bundle(self):
        self.assertIsNone(share._pending_after(chain(("a1", None)), None))


class FindBundleTests(unittest.TestCase):
    def test_prefers_exact_name_then_newest_icloud_copy(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(share.find_bundle(d))
            old, new = os.path.join(d, "krx_full_data(1).zip"), os.path.join(d, "krx_full_data(2).zip")
            for path, mtime in ((old, 1000), (new, 2000)):
                open(path, "wb").close()
                os.utime(path, (mtime, mtime))
            self.assertEqual(share.find_bundle(d), new)
            exact = os.path.join(d, "krx_full_data.zip")
            open(exact, "wb").close()
            self.assertEqual(share.find_bundle(d), exact)


class ShareRoundTripTests(unittest.TestCase):
    """Mac에서 만든 일일 시세 파일을 다른 PC의 데이터 폴더에 반영한다."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = temp.name
        self.share_dir = os.path.join(self.root, "share")
        self.mac = os.path.join(self.root, "mac")
        self.win = os.path.join(self.root, "win")

    def use(self, base):
        dirs = {
            "RAW_DAILY_DIR": os.path.join(base, "raw", "daily"),
            "DAILY_CLOSE_DIR": os.path.join(base, "daily_close"),
            "MASTER_DIR": os.path.join(base, "master"),
            "MASTER_FILE": os.path.join(base, "master", "kospi_tickers.csv"),
            "INDEX_DIR": os.path.join(base, "index"),
            "INDEX_WEEKLY_DIR": os.path.join(base, "index", "weekly"),
            "INDEX_MONTHLY_DIR": os.path.join(base, "index", "monthly"),
            "DERIVED_DAILY_DIR": os.path.join(base, "derived", "daily"),
            "DERIVED_WEEKLY_DIR": os.path.join(base, "derived", "weekly"),
            "DERIVED_MONTHLY_DIR": os.path.join(base, "derived", "monthly"),
            "LOG_DIR": os.path.join(base, "logs"),
        }
        patchers = [mock.patch.object(ds, k, v) for k, v in dirs.items()]
        patchers += [
            mock.patch.object(share, "DATA_DIR", base),
            mock.patch.object(share, "OUTPUT_DIR", os.path.join(base, "output")),
        ]
        for p in patchers:
            p.start()
        ds.ensure_dirs()
        return patchers

    def stop(self, patchers):
        for p in patchers:
            p.stop()

    def rows(self, code, mode, dates, close):
        df = pd.DataFrame({
            "date": pd.to_datetime(dates), "open": close, "high": close, "low": close,
            "close": close, "volume": 10, "asof_datetime": "x", "asof_date": "x",
            "asof_time": "x", "price_status": "종가",
        })
        df.insert(0, "mode", mode)
        df.insert(0, "name", "가")
        df.insert(0, "code", code)
        return df

    def test_full_then_daily_files(self):
        mac = self.use(self.mac)
        ds.apply_daily_rows(self.rows("000001", "full", ["2026-11-02"], 100))
        ds.write_daily_close(self.rows("000001", "full", ["2026-11-02"], 100), [])
        st = share.export_share(self.share_dir)
        self.assertEqual(st["full_rebuilt"], "없음")
        self.stop(mac)

        win = self.use(self.win)
        with mock.patch.object(ds, "generate_derived_all") as derive:
            self.assertTrue(share.import_share(self.share_dir, scan=False))
            self.assertFalse(share.import_share(self.share_dir, scan=False))
        derive.assert_not_called()
        self.stop(win)

        mac = self.use(self.mac)
        delta = self.rows("000001", "incr", ["2026-11-03"], 110)
        ds.write_daily_close(delta, [])
        ds.apply_daily_rows(delta)
        st = share.export_share(self.share_dir)
        self.assertIsNone(st["full_rebuilt"])
        self.assertEqual(len(st["daily_copied"]), 1)
        self.stop(mac)

        win = self.use(self.win)
        with mock.patch.object(ds, "generate_derived_all") as derive:
            self.assertTrue(share.import_share(self.share_dir, scan=False))
        self.assertEqual(derive.call_args.args[0], [("000001", "가")])
        got = ds.load_raw_daily(ds.raw_file_path("000001", "가"))
        self.assertEqual(list(got["close"]), [100, 110])
        self.stop(win)


if __name__ == "__main__":
    unittest.main()
