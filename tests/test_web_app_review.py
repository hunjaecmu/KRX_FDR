import os
import sys
import tempfile
import unittest
from unittest import mock

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import streamlit_image_select
from streamlit.testing.v1 import AppTest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from webapp import storage

MENU = "3. 서칭 데이터 조회"
CASE = "weekly_ma10_breakout"
OTHER_CASE = "weekly_ma240_breakout"
IDX = f"gallery_idx_{CASE}"


class FakeImageSelect:
    """실제 부품과 같은 동작: 클릭 전에는 index, 클릭 후에는 위젯 키별 마지막 클릭값을 반환."""

    def __init__(self):
        self.clicked = {}
        self.keys = []
        self.captions = []

    def __call__(self, label, images, captions=None, index=0, use_container_width=True,
                 return_value="original", key=None):
        self.keys.append(key)
        self.captions.append(list(captions or []))
        return self.clicked.get(key, index)

    def click(self, value):
        self.clicked[self.keys[-1]] = value


class ReviewGalleryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        cls.output = temp.name
        scan = os.path.join(cls.output, "scan_result_20261102_100000")
        rows = []
        for case in (CASE, OTHER_CASE):
            chart_dir = os.path.join(scan, "charts", case)
            os.makedirs(chart_dir)
        for i in range(11):
            code = f"{i + 1:06d}"
            # The last two are swapped so that strength order differs from code order.
            # The 11th is below the minimum breakout and must not be shown.
            pct = {8: 10, 9: 9, 10: 0.5}.get(i, i + 1) * 0.8
            rows.append({
                "scan_case": CASE, "scan_label": "주봉 10이평 돌파", "code": code, "name": f"종목{i}",
                "date": "2026-11-06", "breakout_strength": pct / 100, "breakout_pct": pct, "volume_pct": 10.0,
            })
            fig = plt.figure(figsize=(0.2, 0.2))
            fig.savefig(os.path.join(scan, "charts", CASE, f"{code}_종목{i}_weekly_{CASE}.png"))
            plt.close(fig)
        pd.DataFrame(rows).to_csv(os.path.join(scan, "all_breakouts.csv"), index=False, encoding="utf-8-sig")

    def setUp(self):
        self.fake = FakeImageSelect()
        self.saved = []
        weekly = pd.DataFrame({"date": pd.to_datetime(["2026-11-06"]), "close": [100.0]})
        for patcher in (
            mock.patch.object(streamlit_image_select, "image_select", self.fake),
            mock.patch("config.OUTPUT_DIR", self.output),
            mock.patch("data_loader.load_weekly", return_value=weekly),
            mock.patch.object(storage, "append_row", lambda path, row: self.saved.append(row)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.at = AppTest.from_file(os.path.join(ROOT, "web_app.py"), default_timeout=60)
        self.at.query_params["menu"] = MENU
        self.at.run()
        self.assertEqual(len(self.at.exception), 0)

    @property
    def idx(self):
        return self.at.session_state[IDX]

    def next(self):
        self.at.button(key=f"next_{CASE}").click().run()

    def click_thumb(self, value):
        self.fake.click(value)
        self.at.run()

    def test_next_twice_after_thumbnail_click_does_not_jump_back(self):
        self.click_thumb(3)
        self.assertEqual(self.idx, 3)
        self.next()
        self.next()
        self.assertEqual(self.idx, 5)

    def test_save_after_thumbnail_and_next_keeps_position_and_message(self):
        self.click_thumb(3)
        self.next()
        self.at.button(key=f"review_interest_save_{CASE}").click().run()
        # 강도 내림차순: 000009, 000010, 000008, 000007, 000006, ...
        self.assertEqual(self.saved[-1]["종목코드"], "000006")
        self.assertEqual(self.idx, 4)
        self.assertEqual(len(self.at.success), 1)

    def test_same_thumbnail_can_be_clicked_again_after_moving(self):
        self.click_thumb(3)
        self.next()
        self.click_thumb(3)
        self.assertEqual(self.idx, 3)

    def test_filter_change_resets_position_and_recreates_thumbnails(self):
        self.click_thumb(7)
        key_before = self.fake.keys[-1]
        self.at.selectbox[1].select("최대 5.0%").run()
        self.assertEqual(self.idx, 0)
        self.assertNotEqual(self.fake.keys[-1], key_before)

    def test_sort_change_recreates_thumbnails(self):
        key_before = self.fake.keys[-1]
        self.at.selectbox[0].select("코드순").run()
        self.assertNotEqual(self.fake.keys[-1], key_before)

    def test_previous_button_enabled_right_after_next(self):
        self.next()
        self.assertEqual(self.idx, 1)
        self.assertFalse(self.at.button(key=f"prev_{CASE}").disabled)

    def test_next_button_disabled_right_after_reaching_last(self):
        self.click_thumb(8)
        self.next()
        self.assertEqual(self.idx, 9)
        self.assertTrue(self.at.button(key=f"next_{CASE}").disabled)

    def test_case_button_highlight_follows_click_immediately(self):
        self.at.button(key=f"case_sel_{OTHER_CASE}").click().run()
        self.assertEqual(self.at.button(key=f"case_sel_{OTHER_CASE}").proto.type, "primary")
        self.assertEqual(self.at.button(key=f"case_sel_{CASE}").proto.type, "secondary")

    def test_memo_does_not_carry_over_to_next_stock(self):
        self.at.text_input(key=f"review_interest_memo_{CASE}_000009").input("A 메모").run()
        self.next()
        self.assertEqual(self.at.text_input(key=f"review_interest_memo_{CASE}_000010").value, "")

    def test_strength_sort_is_descending_and_hides_small_breakouts(self):
        codes = [caption.split(" | ")[0] for caption in self.fake.captions[-1]]
        self.assertEqual(codes[:3], ["000009", "000010", "000008"])
        self.assertEqual(codes[-1], "000001")
        self.assertNotIn("000011", codes)


class ChartsOnlyScanTests(unittest.TestCase):
    def test_missing_all_breakouts_renders_without_error(self):
        with tempfile.TemporaryDirectory() as output:
            chart_dir = os.path.join(output, "scan_result_20261102_110000", "charts", CASE)
            os.makedirs(chart_dir)
            fig = plt.figure(figsize=(0.2, 0.2))
            fig.savefig(os.path.join(chart_dir, f"000001_종목_weekly_{CASE}.png"))
            plt.close(fig)
            with mock.patch("config.OUTPUT_DIR", output), \
                    mock.patch.object(streamlit_image_select, "image_select", FakeImageSelect()):
                at = AppTest.from_file(os.path.join(ROOT, "web_app.py"), default_timeout=60)
                at.query_params["menu"] = MENU
                at.run()
            self.assertEqual(len(at.exception), 0)
            self.assertTrue(any("N/A" in c.value for c in at.caption))


if __name__ == "__main__":
    unittest.main()
