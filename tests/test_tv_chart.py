import json
import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webapp import tv_chart


def bars() -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.to_datetime(["2026-10-16", "2026-10-23", "2026-10-30", "2026-11-06"]),
        "open": [100.0, 110.0, 120.0, 130.0],
        "high": [115.0, 125.0, 135.0, 145.0],
        "low": [95.0, 105.0, 115.0, 125.0],
        "close": [110.0, 105.0, 130.0, 140.0],
        "volume": [1000, 0, 3000, 4000],
        "ma5": [None, 107.5, 115.0, 121.0],
        "ma10": [None, None, None, None],
    })


class BuildPayloadTests(unittest.TestCase):
    def payload(self, target="2026-10-30", **kwargs):
        return tv_chart.build_payload(bars(), pd.Timestamp(target), "제목", 2, **kwargs)

    def test_bars_after_target_date_are_not_included(self):
        payload = self.payload()
        self.assertEqual(payload["anchor"], "2026-10-30")
        self.assertEqual(payload["candles"][-1]["time"], "2026-10-30")
        self.assertNotIn("2026-11-06", json.dumps(payload))

    def test_anchor_uses_last_bar_before_target(self):
        self.assertEqual(self.payload("2026-10-28")["anchor"], "2026-10-23")

    def test_no_bars_before_target_raises(self):
        with self.assertRaises(ValueError):
            self.payload("2020-01-01")

    def test_volume_color_follows_candle_direction(self):
        volumes = self.payload()["volumes"]
        self.assertEqual(volumes[0]["color"], tv_chart.UP_COLOR)
        self.assertEqual(volumes[1]["color"], tv_chart.DOWN_COLOR)

    def test_moving_average_skips_missing_values(self):
        moving_averages = self.payload()["moving_averages"]
        self.assertEqual([p["time"] for p in moving_averages["MA5"]["data"]], ["2026-10-23", "2026-10-30"])
        self.assertNotIn("MA10", moving_averages)

    def test_marker_moves_to_last_bar_on_or_before_date(self):
        payload = self.payload(marker_date=pd.Timestamp("2026-10-20"))
        self.assertEqual(payload["markers"][0]["time"], "2026-10-16")

    def test_marker_before_all_data_is_omitted(self):
        self.assertEqual(self.payload(marker_date=pd.Timestamp("2020-01-01"))["markers"], [])


class RenderHtmlTests(unittest.TestCase):
    def test_title_cannot_close_script_tag(self):
        payload = tv_chart.build_payload(bars(), pd.Timestamp("2026-10-30"), "</script><b>x", 2)
        rendered = tv_chart.render_html(payload)
        self.assertNotIn("</script><b>x", rendered)
        self.assertIn("LightweightCharts", rendered)

    def test_attribution_logo_stays_on(self):
        payload = tv_chart.build_payload(bars(), pd.Timestamp("2026-10-30"), "t", 2)
        self.assertIn("attributionLogo: true", tv_chart.render_html(payload))


if __name__ == "__main__":
    unittest.main()
