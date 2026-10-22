from __future__ import annotations

import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import thesis_evidence as thesis


class ThesisParseCacheTests(unittest.TestCase):
    def setUp(self):
        thesis._document_period_values.cache_clear()

    def test_exact_content_parse_reuse_and_changed_period(self):
        original = thesis._DocumentPeriod.feed
        calls = []
        def feed(parser, raw):
            calls.append(raw)
            return original(parser, raw)
        one = '<ix:nonnumeric name="dei:DocumentPeriodEndDate">2026-06-30</ix:nonnumeric>'
        two = one.replace('2026-06-30', '2026-09-30')
        with patch.object(thesis._DocumentPeriod, 'feed', feed):
            self.assertEqual(thesis._document_period_values(one), {'2026-06-30'})
            self.assertEqual(thesis._document_period_values(one), {'2026-06-30'})
            self.assertEqual(thesis._document_period_values(two), {'2026-09-30'})
        self.assertEqual(calls, [one, two])
        both = one + two
        self.assertEqual(thesis._document_period_values(both), {'2026-06-30', '2026-09-30'})
        self.assertNotEqual(thesis._document_period_values(both), {'2026-06-30'})

    def test_parse_cache_is_bounded_and_does_not_cache_a_locator(self):
        for day in range(1, 12):
            raw = f'<ix:nonnumeric name="dei:DocumentPeriodEndDate">2026-06-{day:02}</ix:nonnumeric>'
            self.assertEqual(thesis._document_period_values(raw), {f'2026-06-{day:02}'})
        info = thesis._document_period_values.cache_info()
        self.assertEqual(info.maxsize, 8)
        self.assertEqual(info.currsize, 8)


if __name__ == '__main__':
    unittest.main()
