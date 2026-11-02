import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webapp import workflow

MONDAY = date(2026, 11, 2)


def states(trade_date, collected, scan_label, today=MONDAY):
    steps = workflow.build_steps(
        {"latest_trade_date": trade_date, "latest_collection_date": collected},
        {"latest_scan_label": scan_label, "total_breakouts": 287},
        today,
    )
    return [step["state"] for step in steps]


class BuildStepsTests(unittest.TestCase):
    def test_all_done_when_scan_is_after_collection(self):
        self.assertEqual(
            states("2026-11-02", "2026-11-02 21:17:52", "20261102_223343"),
            [workflow.DONE, workflow.DONE, workflow.DONE],
        )

    def test_scan_needed_when_scan_is_before_collection(self):
        self.assertEqual(
            states("2026-11-02", "2026-11-02 21:17:52", "20261030_190000"),
            [workflow.DONE, workflow.TODO, workflow.WAITING],
        )

    def test_old_data_needs_update_first(self):
        self.assertEqual(
            states("2026-10-30", "2026-10-30 21:00:00", "20261030_220000"),
            [workflow.TODO, workflow.WAITING, workflow.WAITING],
        )

    def test_friday_data_is_current_on_sunday(self):
        self.assertEqual(
            states("2026-11-06", "2026-11-06 21:00:00", "20261106_220000", today=date(2026, 11, 8)),
            [workflow.DONE, workflow.DONE, workflow.DONE],
        )

    def test_no_data_and_no_scan(self):
        self.assertEqual(
            states(None, None, "미실행"),
            [workflow.TODO, workflow.WAITING, workflow.WAITING],
        )

    def test_scan_never_run_with_current_data(self):
        self.assertEqual(
            states("2026-11-02", "2026-11-02 21:00:00", "미실행"),
            [workflow.DONE, workflow.TODO, workflow.WAITING],
        )


if __name__ == "__main__":
    unittest.main()
