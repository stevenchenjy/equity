"""Display migration must preserve research meaning and delivery identity."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from email.utils import parseaddr
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import equity_naming as naming
import phase5r_email_brief as brief
import send_phase5r_daily_email as sender
from phase5r_daily_common import recommendation_notification_fingerprint
from test_phase5r_email_brief import action_fixture
from test_phase5r_owner_review_delivery import owner_review_fixture


class NamingCompatibilityTests(unittest.TestCase):
    def test_new_brand_overrides_legacy_display_without_changing_address_or_class(self):
        decision = owner_review_fixture()
        before = copy.deepcopy(decision)
        config = {'sender_name': 'Phase 5R Equity Brief', 'smtp_username': 'sender@example.com',
                  'recipient_email': 'recipient@example.com', 'smtp_app_password': 'offline-value-never-sent'}
        with tempfile.TemporaryDirectory() as directory:
            text, html = Path(directory)/'brief.txt', Path(directory)/'brief.html'
            text.write_text('Local body\n'); html.write_text('<p>Local body</p>\n')
            with patch.object(sender, 'DAILY_BRIEF_TEXT_PATH', text), patch.object(sender, 'DAILY_BRIEF_HTML_PATH', html), \
                 patch.object(sender, 'load_config', side_effect=AssertionError('private config prohibited')), \
                 patch.object(sender.smtplib, 'SMTP', side_effect=AssertionError('network prohibited')):
                for legacy in (False, True):
                    value = copy.deepcopy(decision)
                    if legacy: value.pop('email_brief_version')
                    for flags, prefix in (({}, '[Equity]'), ({'correction': True}, '[Equity 更正版]'),
                                          ({'owner_review': True}, '[Equity 应请求复核]')):
                        with self.subTest(legacy=legacy, flags=flags):
                            message = sender.build_message(config, value, **flags)
                            self.assertEqual(parseaddr(str(message['From'])), ('Equity Research', 'sender@example.com'))
                            self.assertEqual(str(message['To']), 'recipient@example.com')
                            self.assertTrue(str(message['Subject']).startswith(prefix))
                            self.assertNotIn('Phase 5R', str(message['Subject']))
                            self.assertEqual(sender.cycle_is_blocked([{'cycle_date': value['cycle_date'], 'status': 'sent'}], value['cycle_date']), (True, 'sent'))
        self.assertEqual(decision, before)

    def test_presentation_change_preserves_decision_view_and_notification_fingerprint(self):
        decision = action_fixture()
        before = copy.deepcopy(decision)
        view = brief.build_email_view(decision)
        fingerprint = recommendation_notification_fingerprint(decision)
        current = brief.render_email(decision)
        legacy_names = copy.deepcopy(naming.DISPLAY_NAMES)
        legacy_names.update(brand='Phase 5R Equity Brief', subject_label='Phase 5R')
        with patch.object(naming, 'DISPLAY_NAMES', legacy_names):
            legacy = brief.render_email(decision)
            self.assertEqual(brief.build_email_view(decision), view)
            self.assertEqual(recommendation_notification_fingerprint(decision), fingerprint)
        self.assertEqual(current[1], legacy[1].replace('[Phase 5R]', '[Equity]'))
        self.assertEqual(current[2], legacy[2].replace('[Phase 5R]', '[Equity]').replace('Phase 5R Equity Brief', 'Equity Research'))
        self.assertEqual(decision, before)

    def test_display_configuration_rejects_header_and_notification_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'names.json'
            for field in ('brand', 'subject_label', 'alert_message'):
                value = copy.deepcopy(naming.DISPLAY_NAMES)
                value[field] = 'Name\r\nBcc: unexpected@example.com'
                path.write_text(json.dumps(value))
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'invalid_display_name_text'):
                    naming.load_display_names(path)


if __name__ == '__main__':
    unittest.main()
