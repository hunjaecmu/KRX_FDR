import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webapp import auto_publish

CONFIGURED = {"KRX_DATA_REPO": "o/r", "KRX_DATA_TOKEN": "t"}


class IsFullUpdateTests(unittest.TestCase):
    def test_all_markets_or_none_is_full(self):
        self.assertTrue(auto_publish.is_full_update(None))
        self.assertTrue(auto_publish.is_full_update([]))
        self.assertTrue(auto_publish.is_full_update(["KOSPI", "KOSDAQ", "ETF"]))
        self.assertTrue(auto_publish.is_full_update(["etf", "kospi", "kosdaq"]))

    def test_single_market_is_not_full(self):
        self.assertFalse(auto_publish.is_full_update(["KOSPI"]))
        self.assertFalse(auto_publish.is_full_update(["KOSPI", "ETF"]))


class PublishAfterTests(unittest.TestCase):
    def test_skips_without_settings(self):
        env = {k: v for k, v in os.environ.items() if k not in CONFIGURED}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(auto_publish.subprocess, "call") as call:
            self.assertFalse(auto_publish.publish_after("스캔"))
        call.assert_not_called()

    def test_runs_publish_script(self):
        with mock.patch.dict(os.environ, CONFIGURED), \
                mock.patch.object(auto_publish.subprocess, "call", return_value=0) as call:
            self.assertTrue(auto_publish.publish_after("스캔"))
        self.assertTrue(call.call_args.args[0][-1].endswith("publish_lite_data.py"))

    def test_upload_failure_does_not_raise(self):
        with mock.patch.dict(os.environ, CONFIGURED), \
                mock.patch.object(auto_publish.subprocess, "call", return_value=1):
            self.assertFalse(auto_publish.publish_after("스캔"))

    def test_start_failure_does_not_raise(self):
        with mock.patch.dict(os.environ, CONFIGURED), \
                mock.patch.object(auto_publish.subprocess, "call", side_effect=OSError("x")):
            self.assertFalse(auto_publish.publish_after("스캔"))


if __name__ == "__main__":
    unittest.main()
