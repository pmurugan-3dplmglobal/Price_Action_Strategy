import sys, os
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
COMMON_DIR = os.path.join(PROJECT_ROOT, 'common')
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import unittest
import pandas as pd
import numpy as np
from datetime import datetime as dt, timedelta

from common import pattern_funnel
from common.resolve import is_anchor_valid_and_active
from common.targets import find_profit_targets

class TestStaleAnchorEviction(unittest.TestCase):
    def setUp(self):
        pattern_funnel.clear_funnel('test_engine')

    def tearDown(self):
        pattern_funnel.clear_funnel('test_engine')

    def test_bfo_quote_resolution_and_runaway(self):
        b_item = {
            'symbol': 'SENSEX',
            'contract': 'SENSEX2691074700PE',
            'side': 'PE',
            'benchmark': 100.0,
            'current_sl': 80.0,
            't1': 150.0,
            'stage': pattern_funnel.STAGE_B,
            'candle_a_time': '2026-09-08 15:30:00'
        }
        pattern_funnel.promote_item('test_engine', b_item, pattern_funnel.STAGE_B)
        state = pattern_funnel.load_funnel_state('test_engine')
        self.assertEqual(len(state['category_b']), 1)

        # Normal quote
        ltp_normal = {'BFO:SENSEX2691074700PE': 95.0}
        pattern_funnel.purge_invalidated_or_triggered('test_engine', ltp_dict=ltp_normal)
        state = pattern_funnel.load_funnel_state('test_engine')
        self.assertEqual(len(state['category_b']), 1)

        # Runaway quote
        ltp_runaway = {'BFO:SENSEX2691074700PE': 145.0}
        pattern_funnel.purge_invalidated_or_triggered('test_engine', ltp_dict=ltp_runaway)
        state = pattern_funnel.load_funnel_state('test_engine')
        self.assertEqual(len(state['category_b']), 0, 'BFO contract was not evicted despite reaching runaway target threshold!')

    def test_category_b_without_t1_runaway(self):
        b_item = {
            'symbol': 'SENSEX',
            'contract': 'SENSEX2691074700PE',
            'side': 'PE',
            'benchmark': 100.0,
            'current_sl': 80.0,
            't1': None,
            'stage': pattern_funnel.STAGE_B,
            'candle_a_time': '2026-09-10 09:30:00'
        }
        pattern_funnel.promote_item('test_engine', b_item, pattern_funnel.STAGE_B)

        ltp_runaway = {'BFO:SENSEX2691074700PE': 130.0}
        pattern_funnel.purge_invalidated_or_triggered('test_engine', ltp_dict=ltp_runaway)
        state = pattern_funnel.load_funnel_state('test_engine')
        self.assertEqual(len(state['category_b']), 0, 'Category B item without T1 was not evicted on benchmark runaway!')

    def test_target_exhaustion_on_historical_candles(self):
        dates = pd.date_range('2026-09-08 09:15', periods=10, freq='15min')
        df = pd.DataFrame({
            'date': dates,
            'open':  [22.0, 24.0, 25.0, 26.0, 45.0, 80.0, 100.0, 95.0, 90.0, 85.0],
            'high':  [24.0, 26.0, 27.0, 28.0, 115.0, 105.0, 110.0, 98.0, 92.0, 88.0],
            'low':   [21.0, 23.0, 24.0, 25.0, 40.0, 75.0, 85.0, 88.0, 85.0, 80.0],
            'close': [23.5, 25.5, 26.0, 27.0, 102.0, 95.0, 90.0, 89.0, 86.0, 82.0]
        })

        candle_a_time = str(dates[2])
        entry_price = 26.0
        sl_val = 21.0
        t1, t2, t3 = find_profit_targets(df, entry_price, stop_loss=sl_val)
        self.assertIsNotNone(t1)

        is_active = is_anchor_valid_and_active(df, candle_a_time, sl_val, t1, t2_target=t2, entry_price=entry_price, side='BULL')
        self.assertFalse(is_active, 'Anchor should have been recognized as EXHAUSTED / completed!')

if __name__ == '__main__':
    unittest.main()
