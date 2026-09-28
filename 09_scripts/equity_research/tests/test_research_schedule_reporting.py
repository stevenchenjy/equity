from __future__ import annotations

import copy
import unittest
from datetime import datetime

from _support import SCRIPT_DIR  # noqa: F401
from capital_work_queue import build_capital_work_queue, compact_summary
from test_capital_work_queue import decision
from work_queue_reporting import cash_lines


class ResearchScheduleReportingTests(unittest.TestCase):
    def test_inflight_publication_refresh_does_not_promise_later_retry(self):
        # The composer runs before its parent retires the remaining retry slots.
        current = datetime.fromisoformat("2026-09-28T11:21:20-04:00")
        payload = decision()
        payload["generated_at"] = current.isoformat()
        scheduler = {"dates": {"2026-09-28": {
            "refresh_slots_completed": ["08:15", "11:15"],
        }}}
        before = copy.deepcopy(scheduler)
        queue = build_capital_work_queue(payload, None, current=current, scheduler_state=scheduler)
        self.assertEqual(queue["next_automatic_review_at"], "2026-09-29T08:15:00-04:00")
        self.assertEqual(scheduler, before)
        text = " ".join(cash_lines({"capital_work_queue": compact_summary(queue)}))
        self.assertIn("Next routine research window", text)
        self.assertIn("schedule as of 2026-09-28T11:21:20-04:00", text)
        self.assertIn("conditional recovery", text)
        self.assertNotIn("2026-09-28T11:45", text)

    def test_weekday_and_weekend_routine_boundaries_remain_accurate(self):
        for stamp, expected in [
            ("2026-09-28T08:20:00-04:00", "2026-09-28T11:15:00-04:00"),
            ("2026-09-26T11:21:00-04:00", "2026-09-27T11:15:00-04:00"),
        ]:
            with self.subTest(stamp=stamp):
                current = datetime.fromisoformat(stamp)
                payload = decision()
                payload["generated_at"] = stamp
                queue = build_capital_work_queue(payload, None, current=current)
                self.assertEqual(queue["next_automatic_review_at"], expected)


if __name__ == "__main__":
    unittest.main()
