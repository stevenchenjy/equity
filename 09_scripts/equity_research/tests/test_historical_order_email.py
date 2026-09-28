import copy
import unittest
from _support import SCRIPT_DIR  # noqa: F401
from scheduled_email import cards


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
        self.assertIn('no-orders page observed at 2026-09-28T14:54:00-04:00',text)
        self.assertNotIn('pending in snapshot',text)

    def test_expired_snapshot_never_implies_current_remaining_quantity(self):
        text = self.render({'ticker':'TEST','status':'pending','remaining_quantity':2,
            'quantity':2,'side':'sell','review_status':'expired_pending_verification'})
        self.assertIn('Current status and remaining quantity are unverified',text)
        self.assertNotIn('pending in snapshot',text)

    def test_ordinary_pending_and_terminal_records_keep_their_distinction(self):
        self.assertIn('pending in snapshot',self.render({'ticker':'TEST','status':'pending','quantity':2}))
        self.assertIn('Historical terminal records: TEST filled',self.render({'ticker':'TEST','status':'filled'}))

    def test_recorded_empty_inventory_survives_without_any_historical_ticket(self):
        observation = {'as_of': '2026-09-28T14:54:00-04:00', 'complete': True,
                       'orders_shown': [], 'statement': "You don't have any orders."}
        decision = {'tactical_review': {'open_orders': {'orders': [],
                    'current_inventory_observation': observation}}}
        text = next(c['body'] for c in cards(decision, {'plans': []}) if c['title']=='Orders and proposals')
        self.assertIn('Broker page observation at 2026-09-28T14:54:00-04:00: no orders shown then', text)
        observation['complete'] = False
        text = next(c['body'] for c in cards(decision, {'plans': []}) if c['title']=='Orders and proposals')
        self.assertNotIn('no orders shown then', text)


if __name__ == '__main__':
    unittest.main()
