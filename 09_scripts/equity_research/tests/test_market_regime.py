from __future__ import annotations

import copy
import unittest

from _support import SCRIPT_DIR
from daily_common import read_json
from market_regime import POLICY_PATH, build_regime


class MarketRegimeTests(unittest.TestCase):
    def setUp(self):
        self.policy = read_json(POLICY_PATH)
        self.universe = [{"ticker": ticker, "is_benchmark": "yes" if ticker in {"SPY", "QQQ"} else "no"}
                         for ticker in ["SPY", "QQQ", *[f"T{i}" for i in range(12)]]]

    def run_day(self, day, prior=None, stress=False, stale=False):
        session = f"2026-09-{day:02}"
        rows = [{"ticker": row["ticker"], "last_price": "70" if stress else "99",
                 "fifty_two_week_high": "100", "intraday_change_pct": "-4" if stress else "1",
                 "data_quality_label": "ok", "market_session_date": "2026-08-01" if stale else session}
                for row in self.universe]
        return build_regime(rows, self.universe, prior or {}, self.policy, session, session + "T17:00:00-04:00")

    def test_two_distinct_stress_closes_and_three_recovery_closes(self):
        first = self.run_day(14, stress=True)
        repeat = self.run_day(14, first, stress=True)
        self.assertEqual((first["regime"], repeat["regime"]), ("caution", "caution"))
        confirmed = self.run_day(15, repeat, stress=True)
        self.assertEqual((confirmed["regime"], confirmed["required_distinct_closes"]), ("stress", 3))
        state = self.run_day(16, confirmed)
        self.assertEqual(state["regime"], "stress")
        state = self.run_day(17, state)
        self.assertEqual(state["regime"], "stress")
        state = self.run_day(18, state)
        self.assertEqual((state["regime"], state["required_distinct_closes"]), ("normal", 2))
        self.assertFalse(state["holding_exit_authority"])
        self.assertFalse(state["hard_risk_caps_changed"])

    def test_stale_prices_never_claim_current_context(self):
        result = self.run_day(18, stale=True)
        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["regime"], "unknown")

    def test_missing_or_nonfinite_benchmark_is_insufficient(self):
        self.universe = [row for row in self.universe if row["ticker"] != "SPY"]
        self.assertEqual(self.run_day(18)["status"], "insufficient")

    def test_revision_does_not_reuse_old_votes(self):
        first = self.run_day(14, stress=True)
        first["policy_version"] = "old"
        self.assertEqual(self.run_day(15, first, stress=True)["regime"], "caution")

    def test_future_observations_do_not_vote(self):
        future = self.run_day(18, stress=True)
        result = self.run_day(14, future, stress=True)
        self.assertEqual(result["regime"], "caution")
        self.assertEqual(len(result["observations"]), 1)

    def test_duplicate_prior_dates_cannot_confirm_stress(self):
        prior = self.run_day(14, stress=True)
        prior["observations"] *= 4
        self.assertEqual(self.run_day(14, prior, stress=True)["regime"], "caution")

    def test_future_market_session_rejected(self):
        with self.assertRaises(ValueError):
            build_regime([], [], {}, self.policy, "2026-09-21", "2026-09-20T17:00:00-04:00")

    def test_same_session_intraday_observation_cannot_confirm_stress(self):
        prior = self.run_day(17, stress=True)
        rows = [{"ticker": row["ticker"], "last_price": "70", "fifty_two_week_high": "100",
                 "intraday_change_pct": "-4", "data_quality_label": "ok",
                 "market_session_date": "2026-09-18"} for row in self.universe]
        for observed in ("2026-09-18T09:31:00-04:00", "2026-09-18T19:59:00+00:00"):
            with self.subTest(observed=observed), self.assertRaises(ValueError):
                build_regime(rows, self.universe, prior, self.policy, "2026-09-18", observed)

    def test_conflicting_duplicate_quotes_cannot_be_last_row_wins(self):
        rows = [{"ticker": row["ticker"], "last_price": "70", "fifty_two_week_high": "100",
                 "intraday_change_pct": "-4", "data_quality_label": "ok",
                 "market_session_date": "2026-09-18"} for row in self.universe]
        rows.append(dict(rows[0], last_price="99", intraday_change_pct="2"))
        for ordered in (rows, list(reversed(rows))):
            result = build_regime(ordered, self.universe, {}, self.policy,
                                  "2026-09-18", "2026-09-18T17:00:00-04:00")
            self.assertEqual(result["status"], "insufficient")
            self.assertEqual(result["regime"], "unknown")


if __name__ == "__main__":
    unittest.main()
