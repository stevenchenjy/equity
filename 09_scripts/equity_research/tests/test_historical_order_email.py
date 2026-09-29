import copy
import unittest
from _support import SCRIPT_DIR  # noqa: F401
from scheduled_email import cards, owner_check_window


class HistoricalOrderEmailTests(unittest.TestCase):
    def render(self, row):
        decision = {'tactical_review': {'open_orders': {
            'as_of': '2026-09-28T14:54:00-04:00', 'orders': [row]}}}
        before = copy.deepcopy(decision)
        text = next(c['body'] for c in cards(decision, {'plans': []}) if c['title']=='Orders and proposals')
        self.assertEqual(decision, before)
        return text

    def test_historical_reservation_is_not_presented_as_current_pending(self):
        text = self.render({'ticker':'TEST','side':'sell','quantity':2,'remaining_quantity':2,
            'limit_price':42.5,'time_in_force':'DAY','status':'pending',
            'record_scope':'unresolved_historical_reservation','current_status_verified':False,
            'current_inventory_presence':'not_shown_in_current_no_orders_page',
            'last_verified_at':'2026-09-24T21:36:00-04:00'})
        self.assertIn('unresolved historical sell record',text)
        self.assertIn('Local conservative reservation: 2 shares',text)
        self.assertIn('2026-09-24T21:36:00-04:00',text)
        self.assertIn('not shown in the no-orders page observed at 2026-09-28T14:54:00-04:00',text)
        self.assertNotIn('pending in snapshot',text)

    def test_expired_snapshot_never_implies_current_remaining_quantity(self):
        text = self.render({'ticker':'TEST','status':'pending','remaining_quantity':2,
            'quantity':2,'side':'sell','review_status':'expired_pending_verification'})
        self.assertIn('Current status and remaining quantity are unverified',text)
        self.assertNotIn('pending in snapshot',text)

    def test_ordinary_pending_and_terminal_records_keep_their_distinction(self):
        pending = self.render({'ticker':'TEST','status':'pending','quantity':2})
        self.assertIn('pending in snapshot',pending)
        self.assertIn('Replacement: confirm cancellation',pending)
        self.assertIn('Historical terminal records: TEST filled',self.render({'ticker':'TEST','status':'filled'}))

    def test_recorded_empty_inventory_survives_without_any_historical_ticket(self):
        observation = {'as_of': '2026-09-28T14:54:00-04:00', 'complete': True,
                       'orders_shown': [], 'statement': "You don't have any orders."}
        decision = {'tactical_review': {'open_orders': {'orders': [],
                    'current_inventory_observation': observation}}}
        text = next(c['body'] for c in cards(decision, {'plans': []}) if c['title']=='Orders and proposals')
        self.assertIn('Current active orders: none observed at 2026-09-28T14:54:00-04:00', text)
        self.assertNotIn('Replacement: confirm cancellation', text)
        self.assertNotIn('no orders shown then', text)
        observation['complete'] = False
        text = next(c['body'] for c in cards(decision, {'plans': []}) if c['title']=='Orders and proposals')
        self.assertNotIn('Current active orders: none', text)

    def test_after_close_draft_does_not_repeat_expired_quantity_or_owner_window(self):
        decision = {'generated_at':'2026-09-29T16:05:00-04:00','cycle_date':'2026-09-29',
                    'account':{'cash_basis':'owner_recorded'},
                    'tactical_review':{'open_orders':{'orders':[]}}}
        self.assertEqual(owner_check_window(decision),'next 09:45–10:45 ET window')
        rendered = cards(decision,{'plans':[{'ticker':'SPY'}]})
        attention = next(c['body'] for c in rendered if c['title']=='What to do now')
        orders = next(c['body'] for c in rendered if c['title']=='Orders and proposals')
        self.assertIn('SPY research review from this session has expired for execution',attention)
        self.assertNotIn('14:45–15:20 ET account check',attention)
        self.assertNotIn('SPY research candidate: up to',orders)


if __name__ == '__main__':
    unittest.main()
