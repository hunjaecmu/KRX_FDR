import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import requests
from streamlit.testing.v1 import AppTest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import data_loader
from webapp import data_status, lite_data


def write_source_data(data_dir: str, output_dir: str) -> None:
    os.makedirs(os.path.join(data_dir, "master"))
    pd.DataFrame([
        {"code": "000001", "name": "가", "market": "KOSPI"},
        {"code": "0000K0", "name": "나", "market": "ETF/KR"},
    ]).to_csv(os.path.join(data_dir, "master", "kospi_tickers.csv"), index=False, encoding="utf-8-sig")
    for timeframe in ("weekly", "monthly"):
        folder = os.path.join(data_dir, "derived", timeframe)
        os.makedirs(folder)
        for code, name in (("000001", "가"), ("0000K0", "나")):
            pd.DataFrame({
                "date": ["2026-10-30", "2026-11-06"], "open": [1, 2], "high": [3, 4], "low": [1, 1], "close": [2, 3],
                "volume": [10, 20], "ma5": [None, 2.5], "ma10": [None, 2.0], "ma20": [None, None], "ma120": [None, None],
                "ma180": [None, None], "ma240": [None, None], "is_final": [True, False],
                "asof_datetime": ["a", "b"], "asof_date": ["2026-11-02", "2026-11-02"], "asof_time": ["20:00", "20:00"],
                "price_status": ["종가", "종가"],
            }).to_csv(os.path.join(folder, f"{code}_{name}.csv"), index=False, encoding="utf-8-sig")
    scan = os.path.join(output_dir, "scan_result_20261102_100000", "charts", "weekly_ma10_breakout")
    os.makedirs(scan)
    with open(os.path.join(scan, "000001_가.png"), "wb") as f:
        f.write(b"png")
    with open(os.path.join(os.path.dirname(os.path.dirname(scan)), "all_breakouts.csv"), "w", encoding="utf-8") as f:
        f.write("scan_case\n")
    for timeframe in ("weekly", "monthly"):
        index_dir = os.path.join(data_dir, "index", timeframe)
        os.makedirs(index_dir)
        for code, name in (("KS11", "KOSPI"), ("KQ11", "KOSDAQ")):
            shutil.copy(
                os.path.join(data_dir, "derived", timeframe, "000001_가.csv"),
                os.path.join(index_dir, f"{code}_{name}.csv"),
            )
    for code, name, close, change in (("KS11", "KOSPI", 5859.08, 2.2395), ("KQ11", "KOSDAQ", 734.36, -1.5)):
        with open(os.path.join(data_dir, "index", f"{code}_summary.json"), "w", encoding="utf-8") as f:
            json.dump({
                "code": code, "name": name, "date": "2026-11-02", "close": close,
                "change_pct": change, "price_status": "종가",
            }, f)


class SourceDataTestCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = temp.name
        self.src_data = os.path.join(self.root, "src", "data")
        self.src_output = os.path.join(self.root, "src", "output")
        write_source_data(self.src_data, self.src_output)
        self.bundle = os.path.join(self.root, "bundle", lite_data.BUNDLE_NAME)
        for attr, value in {
            "MASTER_FILE": os.path.join(self.src_data, "master", "kospi_tickers.csv"),
            "DERIVED_WEEKLY_DIR": os.path.join(self.src_data, "derived", "weekly"),
            "DERIVED_MONTHLY_DIR": os.path.join(self.src_data, "derived", "monthly"),
            "INDEX_WEEKLY_DIR": os.path.join(self.src_data, "index", "weekly"),
            "INDEX_MONTHLY_DIR": os.path.join(self.src_data, "index", "monthly"),
        }.items():
            patcher = mock.patch.object(data_loader, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.manifest = lite_data.build_bundle(self.src_data, self.src_output, {"kospi_count": 1}, self.bundle)
        self.dst_data = os.path.join(self.root, "dst", "data")
        self.dst_output = os.path.join(self.root, "dst", "output")


class BundleTests(SourceDataTestCase):
    def test_bundle_contents(self):
        with zipfile.ZipFile(self.bundle) as bundle:
            names = set(bundle.namelist())
        self.assertIn("data/lite/prices.parquet", names)
        self.assertIn("data/master/kospi_tickers.csv", names)
        self.assertIn("output/scan_result_20261102_100000/all_breakouts.csv", names)
        self.assertEqual(self.manifest["price_rows"], 16)
        self.assertEqual([s["code"] for s in self.manifest["index_summaries"]], ["KS11", "KQ11"])

    def test_personal_tracking_files_are_never_included(self):
        with zipfile.ZipFile(self.bundle) as bundle:
            self.assertFalse([n for n in bundle.namelist() if "tracking" in n or "holdings" in n or "watch" in n])

    def test_install_replaces_old_scan_and_parquet_matches_csv(self):
        old_scan = os.path.join(self.dst_output, "scan_result_20200101_000000")
        os.makedirs(old_scan)
        lite_data.install_bundle(self.bundle, self.dst_data, self.dst_output, 123)
        self.assertFalse(os.path.exists(old_scan))
        self.assertEqual(lite_data.load_manifest(self.dst_data)["scan"], "scan_result_20261102_100000")

        with mock.patch.object(data_loader, "PRICES_PARQUET", os.path.join(self.dst_data, "lite", "prices.parquet")), \
                mock.patch.object(data_loader, "USE_PARQUET", True):
            from_parquet = data_loader.load_weekly("0000K0")
        with mock.patch.object(data_loader, "USE_PARQUET", False):
            from_csv = data_loader.load_weekly("0000K0")
        pd.testing.assert_frame_equal(
            from_parquet[from_csv.columns].astype(object), from_csv.astype(object), check_dtype=False
        )
        self.assertEqual(from_parquet["is_final"].tolist(), [True, False])

    def test_index_codes_load_from_parquet_and_csv_without_padding(self):
        lite_data.install_bundle(self.bundle, self.dst_data, self.dst_output, 1)
        with mock.patch.object(data_loader, "PRICES_PARQUET", os.path.join(self.dst_data, "lite", "prices.parquet")), \
                mock.patch.object(data_loader, "USE_PARQUET", True):
            self.assertEqual(len(data_loader.load_weekly("KS11")), 2)
            self.assertEqual(len(data_loader.load_monthly("KS11")), 2)
        self.assertEqual(len(data_loader.load_weekly("KQ11")), 2)
        self.assertEqual(len(data_loader.load_monthly("KQ11")), 2)

    def test_rejects_paths_outside_target(self):
        evil = os.path.join(self.root, "evil.zip")
        with zipfile.ZipFile(evil, "w") as bundle:
            bundle.writestr("../../escape.txt", "x")
        with self.assertRaises(ValueError):
            lite_data.install_bundle(evil, self.dst_data, self.dst_output)
        self.assertFalse(os.path.exists(os.path.join(self.root, "escape.txt")))


class DataStatusTests(SourceDataTestCase):
    def test_counts_markets_from_master(self):
        status = data_status.compute_data_status(self.src_data)
        self.assertEqual(status["kospi_count"], 1)
        self.assertEqual(status["markets"]["ETF"]["count"], 1)


class FakeGitHub(BaseHTTPRequestHandler):
    bundle_path = ""
    asset_id = 1
    downloads = 0
    fail = False
    seen_auth = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        FakeGitHub.seen_auth.append(self.headers.get("Authorization"))
        if FakeGitHub.fail:
            self.send_response(500)
            self.end_headers()
        elif self.path.endswith(f"/releases/tags/{lite_data.RELEASE_TAG}"):
            body = json.dumps({"id": 9, "assets": [{"id": FakeGitHub.asset_id, "name": lite_data.BUNDLE_NAME}]}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)
        else:
            FakeGitHub.downloads += 1
            self.send_response(200)
            self.end_headers()
            with open(FakeGitHub.bundle_path, "rb") as f:
                shutil.copyfileobj(f, self.wfile)


class EnsureDataTests(SourceDataTestCase):
    def setUp(self):
        super().setUp()
        FakeGitHub.bundle_path = self.bundle
        FakeGitHub.asset_id = 1
        FakeGitHub.downloads = 0
        FakeGitHub.fail = False
        FakeGitHub.seen_auth = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeGitHub)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.api = f"http://127.0.0.1:{self.server.server_port}"

    def ensure(self):
        return lite_data.ensure_data("o/r", "secret", self.dst_data, self.dst_output, api=self.api)

    def test_downloads_once_then_only_when_asset_changes(self):
        self.assertTrue(self.ensure())
        self.assertFalse(self.ensure())
        self.assertEqual(FakeGitHub.downloads, 1)
        FakeGitHub.asset_id = 2
        self.assertTrue(self.ensure())
        self.assertEqual(FakeGitHub.downloads, 2)
        self.assertEqual(set(FakeGitHub.seen_auth), {"Bearer secret"})

    def test_failure_without_data_raises(self):
        FakeGitHub.fail = True
        with self.assertRaises(requests.RequestException):
            self.ensure()

    def test_failure_keeps_existing_data(self):
        self.ensure()
        FakeGitHub.fail = True
        self.assertFalse(self.ensure())
        self.assertIsNotNone(lite_data.load_manifest(self.dst_data))


class UploadErrorTests(unittest.TestCase):
    def test_error_shows_github_reason_without_token(self):
        response = requests.Response()
        response.status_code = 422
        response._content = json.dumps({"message": "Repository is empty."}).encode()
        with self.assertRaises(RuntimeError) as caught:
            lite_data._check_github_response(response, "릴리스 조회/생성")
        self.assertIn("Repository is empty.", str(caught.exception))
        self.assertIn("422", str(caught.exception))


class CloudEditionTests(SourceDataTestCase):
    def test_entry_point_is_view_only_with_downloaded_data(self):
        lite_data.install_bundle(self.bundle, self.dst_data, self.dst_output, 1)
        manifest_path = os.path.join(self.dst_data, "lite", "manifest.json")
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["indices"], ["KS11", "KQ11"])
        manifest["data_status"] = {
            "kospi_count": 1, "kosdaq_count": 0, "latest_trade_date": "2026-11-02",
            "latest_collection_date": "2026-11-02", "latest_collection_time": "20:00", "daily_file_count": 2, "markets": {},
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        env = {"KRX_DATA_REPO": "o/r", "KRX_APP_EDITION": "cloud"}
        with mock.patch.dict(os.environ, env), \
                mock.patch("config.DATA_DIR", self.dst_data), \
                mock.patch("config.OUTPUT_DIR", self.dst_output), \
                mock.patch.object(lite_data, "ensure_data", return_value=False):
            at = AppTest.from_file(os.path.join(ROOT, "lite", "streamlit_app.py"), default_timeout=60).run()
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        self.assertEqual(
            [b.label for b in at.sidebar.button], ["시작화면", "돌파 종목 조회", "종목 차트 조회", "주요 종목"]
        )

        bars = pd.DataFrame({
            "date": pd.to_datetime(["2026-10-30", "2026-11-06"]),
            "open": [1.0, 2.0], "high": [3.0, 4.0], "low": [1.0, 1.0], "close": [2.0, 3.0], "volume": [10, 20],
        })
        loads = []

        def recording_loader(timeframe):
            def load(code):
                loads.append((code, timeframe))
                return bars
            return load

        with mock.patch.dict(os.environ, env), \
                mock.patch("config.DATA_DIR", self.dst_data), \
                mock.patch("config.OUTPUT_DIR", self.dst_output), \
                mock.patch.object(lite_data, "ensure_data", return_value=False), \
                mock.patch("data_loader.load_weekly", recording_loader("weekly")), \
                mock.patch("data_loader.load_monthly", recording_loader("monthly")):
            at = AppTest.from_file(os.path.join(ROOT, "lite", "streamlit_app.py"), default_timeout=60)
            at.query_params["menu"] = "9"
            at.run()
            self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
            # 메뉴에 들어오면 KOSPI 주봉과 지수 요약이 바로 보인다.
            self.assertEqual(loads[-1], ("KS11", "weekly"))
            self.assertEqual(len(at.get("iframe")), 1)
            self.assertEqual(len(at.get("imgs")), 0)
            labels = [b.label for b in at.main.button]
            self.assertEqual(labels, ["KOSPI", "KOSDAQ", "삼성전자", "SK하이닉스", "삼성전기"])
            summary_html = " ".join(m.value for m in at.markdown)
            self.assertIn("5,859.08", summary_html)
            self.assertIn("+2.24%", summary_html)
            self.assertIn("-1.50%", summary_html)

            at.button(key="major_stock_009150").click().run()
            self.assertEqual(loads[-1], ("009150", "weekly"))
            self.assertEqual(at.button(key="major_stock_009150").proto.type, "primary")

            at.radio(key="major_timeframe").set_value("월봉").run()
            self.assertEqual(loads[-1], ("009150", "monthly"))

            # 다른 항목을 고르면 주봉으로 돌아간다.
            at.button(key="major_stock_KQ11").click().run()
            self.assertEqual(loads[-1], ("KQ11", "weekly"))

            # 메뉴를 다시 고르면 KOSPI 주봉부터 보여 준다.
            at.radio(key="major_timeframe").set_value("월봉").run()
            at.button(key="menu_btn_시작화면").click().run()
            at.button(key="menu_btn_주요 종목").click().run()
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        self.assertEqual(loads[-1], ("KS11", "weekly"))


if __name__ == "__main__":
    unittest.main()
