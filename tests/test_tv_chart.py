import json
import os
import sys
import unittest
from unittest import mock

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chart_viewer
import historical_chart_viewer
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
        self.assertTrue(volumes[0]["rising"])
        self.assertFalse(volumes[1]["rising"])

    def test_moving_average_skips_missing_values(self):
        moving_averages = self.payload()["moving_averages"]
        self.assertEqual([p["time"] for p in moving_averages["MA5"]["data"]], ["2026-10-23", "2026-10-30"])
        self.assertNotIn("MA10", moving_averages)

    def test_required_moving_average_is_kept_without_values(self):
        payload = self.payload(required_mas=("ma10", "ma240"))
        self.assertEqual(payload["moving_averages"]["MA10"]["data"], [])
        self.assertEqual(payload["moving_averages"]["MA240"]["data"], [])

    def test_marker_moves_to_last_bar_on_or_before_date(self):
        payload = self.payload(marker_date=pd.Timestamp("2026-10-20"))
        self.assertEqual(payload["markers"][0]["time"], "2026-10-16")

    def test_marker_before_all_data_is_omitted(self):
        self.assertEqual(self.payload(marker_date=pd.Timestamp("2020-01-01"))["markers"], [])


class PeriodEndTests(unittest.TestCase):
    def test_week_start_date_maps_to_that_week(self):
        # 2023-01-30은 월요일, 그 주 주봉은 2023-02-03(금)
        self.assertEqual(tv_chart.period_end("2023-01-30", "weekly"), pd.Timestamp("2023-02-05"))
        self.assertEqual(tv_chart.period_end("2023-02-03", "weekly"), pd.Timestamp("2023-02-05"))
        self.assertEqual(tv_chart.period_end("2023-02-05", "weekly"), pd.Timestamp("2023-02-05"))

    def test_month_date_maps_to_month_end(self):
        self.assertEqual(tv_chart.period_end("2020-01-01", "monthly"), pd.Timestamp("2020-01-31"))
        self.assertEqual(tv_chart.period_end("2020-1-31", "monthly"), pd.Timestamp("2020-01-31"))

    def test_week_start_shows_bar_of_that_week(self):
        payload = tv_chart.build_payload(bars(), tv_chart.period_end("2026-10-26", "weekly"), "t", 2)
        self.assertEqual(payload["anchor"], "2026-10-30")


class RenderHtmlTests(unittest.TestCase):
    def test_title_cannot_close_script_tag(self):
        payload = tv_chart.build_payload(bars(), pd.Timestamp("2026-10-30"), "</script><b>x", 2)
        rendered = tv_chart.render_html(payload)
        self.assertNotIn("</script><b>x", rendered)
        self.assertIn("LightweightCharts", rendered)

    def test_dark_theme_colors_are_used(self):
        payload = tv_chart.build_payload(bars(), pd.Timestamp("2026-10-30"), "t", 2)
        rendered = tv_chart.render_html(payload, theme=tv_chart.DARK_THEME)
        self.assertIn("background: #0d1117", rendered)
        self.assertIn(tv_chart.DARK_THEME["up"], rendered)

    def test_ma10_line_is_twice_as_thick(self):
        payload = tv_chart.build_payload(bars(), pd.Timestamp("2026-10-30"), "t", 2)
        self.assertIn('lineWidth: name === "MA10" ? 2 : 1', tv_chart.render_html(payload))

    def test_image_charts_draw_ma10_twice_as_thick(self):
        frame = pd.DataFrame({"ma5": [1.0, 2.0], "ma10": [1.0, 2.0], "ma240": [1.0, 2.0]})
        for module, kwargs in ((historical_chart_viewer, {}), (chart_viewer, {"highlight_ma_cols": ["ma240"]})):
            with mock.patch.object(module.mpf, "make_addplot", side_effect=lambda series, **kw: kw) as plot:
                plots = {p["label"]: p["width"] for p in module._build_addplots(frame, **kwargs)}
            self.assertEqual(plot.call_count, 3)
            self.assertEqual(plots["MA10"], module.BASE_MA_WIDTH * 2)
            self.assertEqual(plots["MA5"], module.BASE_MA_WIDTH)

    def test_missing_moving_average_value_shows_nan(self):
        payload = tv_chart.build_payload(bars(), pd.Timestamp("2026-10-30"), "t", 2, required_mas=("ma240",))
        self.assertIn('"NaN"', tv_chart.render_html(payload))

    def test_attribution_logo_stays_on(self):
        payload = tv_chart.build_payload(bars(), pd.Timestamp("2026-10-30"), "t", 2)
        self.assertIn("attributionLogo: true", tv_chart.render_html(payload))


if __name__ == "__main__":
    unittest.main()
