import base64
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit_image_select
from PIL import Image
from streamlit.testing.v1 import AppTest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import web_app_lite
from webapp import storage, thumbnails

CASE = "weekly_ma10_breakout"


class LiteEditionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        cls.output = temp.name
        scan = os.path.join(cls.output, "scan_result_20261102_100000")
        chart_dir = os.path.join(scan, "charts", CASE)
        os.makedirs(chart_dir)
        fig = plt.figure(figsize=(0.2, 0.2))
        fig.savefig(os.path.join(chart_dir, f"000001_종목_weekly_{CASE}.png"))
        plt.close(fig)
        pd.DataFrame([{
            "scan_case": CASE, "scan_label": "주봉", "code": "000001", "name": "종목", "date": "2026-11-06",
            "breakout_strength": 0.01, "breakout_pct": 1.0, "volume_pct": 10.0, "is_final": False,
        }]).to_csv(os.path.join(scan, "all_breakouts.csv"), index=False, encoding="utf-8-sig")

    def run_app(self, menu):
        at = AppTest.from_file(os.path.join(ROOT, "web_app.py"), default_timeout=60)
        at.query_params["menu"] = menu
        at.run()
        self.assertEqual(len(at.exception), 0)
        return at

    def setUp(self):
        self.write = mock.Mock(side_effect=AssertionError("lite edition must not save"))
        for patcher in (
            mock.patch.dict(os.environ, {"KRX_APP_EDITION": "lite"}),
            mock.patch("config.OUTPUT_DIR", self.output),
            mock.patch.object(streamlit_image_select, "image_select", lambda **kw: kw["index"]),
            mock.patch.object(storage, "append_row", self.write),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def menu_labels(self, at):
        return [b.label for b in at.sidebar.button]

    def test_menu_5_to_8_are_removed(self):
        labels = self.menu_labels(self.run_app("0"))
        self.assertEqual(len(labels), 5)
        self.assertFalse(any(label[0] in "5678" for label in labels))
        self.assertIn("4. 종목 차트 조회", labels)

    def test_start_screen_explains_available_data(self):
        at = self.run_app("0")
        text = " ".join(m.value for m in at.markdown)
        self.assertIn("돌파 조건", text)
        self.assertIn("52봉", text)
        self.assertTrue(any("실시간 시세가 아니며" in c.value for c in at.caption))

    def test_start_screen_has_open_source_notice(self):
        at = self.run_app("0")
        self.assertEqual(at.expander[-1].label, "오픈소스 및 면책 고지")
        text = " ".join(m.value for m in at.expander[-1].markdown)
        self.assertIn("Streamlit", text)
        self.assertIn("Pretendard", text)
        self.assertIn("투자 권유가 아닙니다", text)

    def test_notice_lists_every_pinned_package(self):
        with open(os.path.join(ROOT, "lite", "requirements.txt"), encoding="utf-8") as f:
            pinned = [line.strip().split("==") for line in f if line.strip()]
        with open(os.path.join(ROOT, "THIRD_PARTY_NOTICES.md"), encoding="utf-8") as f:
            notice = f.read()
        for package, version in pinned:
            self.assertIn(f"| {version} |", notice, package)

    def test_removed_menu_address_falls_back_to_start(self):
        at = self.run_app("8")
        self.assertEqual(at.session_state["selected_menu"], "시작화면")

    def test_review_gallery_has_no_save_controls(self):
        at = self.run_app("3")
        self.assertTrue(any("000001" in c.value for c in at.caption))
        self.assertEqual([b for b in at.button if "save" in (b.key or "")], [])
        self.assertEqual(len(at.text_input), 0)


class DarkThumbnailTests(unittest.TestCase):
    def test_white_becomes_dark_and_hues_are_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "chart.png")
            Image.fromarray(np.array([[[255, 255, 255], [255, 0, 0], [0, 0, 255]]], dtype=np.uint8)).resize(
                (30, 10), Image.NEAREST
            ).save(path)
            uri = thumbnails.dark_thumbnail_data_uri(path, width=30)
        self.assertTrue(uri.startswith("data:image/jpeg;base64,"))
        pixels = np.asarray(Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))).convert("RGB"), dtype=int)
        white, red, blue = pixels[5, 3], pixels[5, 15], pixels[5, 25]
        self.assertLess(white.max(), 40)
        self.assertGreater(red[0], red[2] + 100)
        self.assertGreater(blue[2], blue[0] + 100)


class FullEditionTests(unittest.TestCase):
    def test_full_edition_keeps_all_menus(self):
        env = {k: v for k, v in os.environ.items() if k != "KRX_APP_EDITION"}
        with mock.patch.dict(os.environ, env, clear=True):
            at = AppTest.from_file(os.path.join(ROOT, "web_app.py"), default_timeout=60).run()
        self.assertEqual(len(at.sidebar.button), 9)
        self.assertNotIn("주요 종목", [b.label for b in at.sidebar.button])


class LauncherTests(unittest.TestCase):
    def test_command_targets_web_app_with_terminal_theme(self):
        command = web_app_lite.build_command(["--server.headless", "true"])
        self.assertTrue(command[4].endswith("web_app.py"))
        self.assertIn("--theme.backgroundColor=#0d1117", command)
        self.assertEqual(command[-2:], ["--server.headless", "true"])


if __name__ == "__main__":
    unittest.main()
