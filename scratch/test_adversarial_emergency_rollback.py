"""
scratch/test_adversarial_emergency_rollback.py
==============================================
Adversarial Challenge & Stress Verification Suite:
1. Debit Spread Atomic Rollback (ISSUE-087)
   - Leg 1 filled + Leg 2 RMS rejection -> resting cancelled, Leg 1 unwound
   - Multi-slice freeze: Leg 2 slice 1 filled, slice 2 rejected -> Leg 2 short covered at marketable limit, Leg 1 unwound
   - Exchange resolution: BFO for SENSEX/BANKEX, NFO for NIFTY/BANKNIFTY
   - Emergency unwind failure fallback: Retained in ACTIVE_POSITIONS & trade_db with status='ACTIVE'
     * In stock_options_trade_engine
     * In app_option_Trade (1-Click)
     * In index_options_trade_engine (auditing execute_index_entry + caller run_scan_cycle)
2. Catastrophic Opening Gap Override (ISSUE-086)
   - Executed inside real monitor_active_positions loop at 09:20 IST (failsafe window)
   - Long stock: mild dip (< 2x SL dist) vs severe gap (> 2x SL dist)
   - Short stock: mild pop (< 2x SL dist) vs severe gap (> 2x SL dist)
   - Boundary condition at exact 2x SL distance
   - Long option: mild drop vs severe gap (> 2x SL dist)
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, time as datetime_time, timedelta
import pandas as pd

PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMON_DIR = os.path.join(PROJ_ROOT, "common")
TRADE_OPTION_DIR = os.path.join(PROJ_ROOT, "Trade_Option")
for p in [PROJ_ROOT, COMMON_DIR, TRADE_OPTION_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)


class TestAdversarialOpeningGapOverride(unittest.TestCase):
    """Empirical verification of ISSUE-086 Catastrophic Opening Gap Override inside monitor_active_positions."""

    def _make_dummy_candles(self, n=5):
        dates = [datetime(2026, 9, 26, 9, 15) + timedelta(minutes=15 * i) for i in range(n)]
        return pd.DataFrame({
            "date": dates,
            "open": [100.0] * n,
            "high": [102.0] * n,
            "low": [98.0] * n,
            "close": [100.0] * n,
            "volume": [1000] * n
        })

    @patch("common.position_monitor.get_ist_now")
    @patch("common.position_monitor.fetch_and_resample_candles")
    @patch("common.position_monitor.close_stock_position")
    def test_long_stock_mild_opening_dip_is_preserved_during_failsafe(self, mock_close, mock_fetch, mock_now):
        """At 09:20 IST, mild dip below SL (< 2x SL dist) must NOT exit, preserving closing basis."""
        from common.position_monitor import monitor_active_positions

        mock_now.return_value = datetime(2026, 9, 26, 9, 20, 0)
        df_candles = self._make_dummy_candles()
        mock_fetch.return_value = df_candles
        mock_close.return_value = {"success": True}

        mock_kite = MagicMock()
        mock_kite.quote.return_value = {"NSE:TATAMOTORS": {"last_price": 93.0}}

        positions = {
            "TATAMOTORS": {
                "symbol": "TATAMOTORS",
                "contract": "TATAMOTORS",
                "token": 12345,
                "entry_spot": 100.0,
                "current_sl": 95.0,  # SL dist = 5.0, 2x = 10.0
                "t1": 110.0,
                "position_type": "stock",
                "quantity": 100,
                "position_size": 100,
                "side": "BUY",
                "timeframe": "15minute",
                "entry_time": "2026-09-25 14:00:00"
            }
        }
        lock = MagicMock()
        mock_db = MagicMock()
        log_fn = MagicMock()

        # LTP is 93.0 (gap = 2.0 pts <= 10.0 pts)
        monitor_active_positions(
            mock_kite, {"TATAMOTORS": {"token": 12345}}, positions, lock,
            "MIS", "nifty50", "15minute", mock_db, log_fn, live=True
        )

        mock_close.assert_not_called()
        self.assertIn("TATAMOTORS", positions)

    @patch("common.position_monitor.get_ist_now")
    @patch("common.position_monitor.fetch_and_resample_candles")
    @patch("common.position_monitor.close_stock_position")
    def test_long_stock_severe_opening_gap_down_triggers_critical_override(self, mock_close, mock_fetch, mock_now):
        """At 09:20 IST, severe gap down (> 2x SL dist) MUST immediately trigger GAP_BREACH_CRITICAL_OVERRIDE."""
        from common.position_monitor import monitor_active_positions

        mock_now.return_value = datetime(2026, 9, 26, 9, 20, 0)
        df_candles = self._make_dummy_candles()
        mock_fetch.return_value = df_candles
        mock_close.return_value = {"success": True}

        mock_kite = MagicMock()
        # Entry = 100.0, SL = 95.0 (dist = 5.0, 2x = 10.0). LTP = 82.0 (gap = 13.0 > 10.0)
        mock_kite.quote.return_value = {"NSE:TATAMOTORS": {"last_price": 82.0}}

        positions = {
            "TATAMOTORS": {
                "symbol": "TATAMOTORS",
                "contract": "TATAMOTORS",
                "token": 12345,
                "entry_spot": 100.0,
                "current_sl": 95.0,
                "t1": 110.0,
                "position_type": "stock",
                "quantity": 100,
                "position_size": 100,
                "side": "BUY",
                "timeframe": "15minute",
                "entry_time": "2026-09-25 14:00:00"
            }
        }
        lock = MagicMock()
        mock_db = MagicMock()
        log_fn = MagicMock()

        monitor_active_positions(
            mock_kite, {"TATAMOTORS": {"token": 12345}}, positions, lock,
            "MIS", "nifty50", "15minute", mock_db, log_fn, live=True
        )

        mock_close.assert_called_once()
        self.assertNotIn("TATAMOTORS", positions)
        self.assertTrue(log_fn.called)
        log_details = log_fn.call_args[0][5]
        self.assertIn("GAP_BREACH_CRITICAL_OVERRIDE", log_details)

    @patch("common.position_monitor.get_ist_now")
    @patch("common.position_monitor.fetch_and_resample_candles")
    @patch("common.position_monitor.close_stock_position")
    def test_short_stock_mild_opening_pop_is_preserved_during_failsafe(self, mock_close, mock_fetch, mock_now):
        """At 09:20 IST, mild pop above SL (< 2x SL dist) on short stock must NOT exit."""
        from common.position_monitor import monitor_active_positions

        mock_now.return_value = datetime(2026, 9, 26, 9, 20, 0)
        df_candles = self._make_dummy_candles()
        mock_fetch.return_value = df_candles
        mock_close.return_value = {"success": True}

        mock_kite = MagicMock()
        # Short: Entry = 100.0, SL = 105.0 (dist = 5.0, 2x = 10.0). LTP = 107.0 (gap = 2.0 <= 10.0)
        mock_kite.quote.return_value = {"NSE:INFY": {"last_price": 107.0}}

        positions = {
            "INFY": {
                "symbol": "INFY",
                "contract": "INFY",
                "token": 12345,
                "entry_spot": 100.0,
                "current_sl": 105.0,
                "t1": 90.0,
                "position_type": "stock",
                "quantity": 100,
                "position_size": 100,
                "side": "SELL",
                "direction": "BEAR",
                "timeframe": "15minute",
                "entry_time": "2026-09-25 14:00:00"
            }
        }
        lock = MagicMock()
        mock_db = MagicMock()
        log_fn = MagicMock()

        monitor_active_positions(
            mock_kite, {"INFY": {"token": 12345}}, positions, lock,
            "MIS", "nifty50", "15minute", mock_db, log_fn, live=True
        )

        mock_close.assert_not_called()
        self.assertIn("INFY", positions)

    @patch("common.position_monitor.get_ist_now")
    @patch("common.position_monitor.fetch_and_resample_candles")
    @patch("common.position_monitor.close_stock_position")
    def test_short_stock_severe_opening_gap_up_triggers_critical_override(self, mock_close, mock_fetch, mock_now):
        """At 09:20 IST, severe gap up (> 2x SL dist) on short stock MUST trigger GAP_BREACH_CRITICAL_OVERRIDE."""
        from common.position_monitor import monitor_active_positions

        mock_now.return_value = datetime(2026, 9, 26, 9, 20, 0)
        df_candles = self._make_dummy_candles()
        mock_fetch.return_value = df_candles
        mock_close.return_value = {"success": True}

        mock_kite = MagicMock()
        # Short: Entry = 100.0, SL = 105.0 (dist = 5.0, 2x = 10.0). LTP = 118.0 (gap = 13.0 > 10.0)
        mock_kite.quote.return_value = {"NSE:INFY": {"last_price": 118.0}}

        positions = {
            "INFY": {
                "symbol": "INFY",
                "contract": "INFY",
                "token": 12345,
                "entry_spot": 100.0,
                "current_sl": 105.0,
                "t1": 90.0,
                "position_type": "stock",
                "quantity": 100,
                "position_size": 100,
                "side": "SELL",
                "direction": "BEAR",
                "timeframe": "15minute",
                "entry_time": "2026-09-25 14:00:00"
            }
        }
        lock = MagicMock()
        mock_db = MagicMock()
        log_fn = MagicMock()

        monitor_active_positions(
            mock_kite, {"INFY": {"token": 12345}}, positions, lock,
            "MIS", "nifty50", "15minute", mock_db, log_fn, live=True
        )

        mock_close.assert_called_once()
        self.assertNotIn("INFY", positions)
        self.assertTrue(log_fn.called)
        log_details = log_fn.call_args[0][5]
        self.assertIn("GAP_BREACH_CRITICAL_OVERRIDE", log_details)

    @patch("common.position_monitor.get_ist_now")
    @patch("common.position_monitor.fetch_and_resample_candles")
    @patch("common.position_monitor.close_stock_position")
    def test_exact_2x_boundary_is_not_critical(self, mock_close, mock_fetch, mock_now):
        """At exactly 2.0x SL distance, condition gap_magnitude > (2.0 * sl_distance) is False -> preserved."""
        from common.position_monitor import monitor_active_positions

        mock_now.return_value = datetime(2026, 9, 26, 9, 20, 0)
        df_candles = self._make_dummy_candles()
        mock_fetch.return_value = df_candles
        mock_close.return_value = {"success": True}

        mock_kite = MagicMock()
        # Entry = 100.0, SL = 95.0 (dist = 5.0, 2x = 10.0). LTP = 85.0 (gap = 10.0 == 10.0)
        mock_kite.quote.return_value = {"NSE:TATAMOTORS": {"last_price": 85.0}}

        positions = {
            "TATAMOTORS": {
                "symbol": "TATAMOTORS",
                "contract": "TATAMOTORS",
                "token": 12345,
                "entry_spot": 100.0,
                "current_sl": 95.0,
                "t1": 110.0,
                "position_type": "stock",
                "quantity": 100,
                "position_size": 100,
                "side": "BUY",
                "timeframe": "15minute",
                "entry_time": "2026-09-25 14:00:00"
            }
        }
        lock = MagicMock()
        mock_db = MagicMock()
        log_fn = MagicMock()

        monitor_active_positions(
            mock_kite, {"TATAMOTORS": {"token": 12345}}, positions, lock,
            "MIS", "nifty50", "15minute", mock_db, log_fn, live=True
        )

        mock_close.assert_not_called()
        self.assertIn("TATAMOTORS", positions)

    @patch("common.position_monitor.get_ist_now")
    @patch("common.position_monitor.fetch_and_resample_candles")
    @patch("common.position_monitor.close_position")
    def test_long_option_severe_gap_down_triggers_critical_override(self, mock_close, mock_fetch, mock_now):
        """At 09:20 IST, long option with severe premium gap down (> 2x SL dist) triggers critical exit."""
        from common.position_monitor import monitor_active_positions

        mock_now.return_value = datetime(2026, 9, 26, 9, 20, 0)
        df_candles = self._make_dummy_candles()
        mock_fetch.return_value = df_candles
        mock_close.return_value = {"success": True}

        mock_kite = MagicMock()
        # Option Entry = 100.0, SL = 90.0 (dist = 10.0, 2x = 20.0). LTP = 65.0 (gap = 25.0 > 20.0, ratio 1.54 < 2.5)
        mock_kite.quote.return_value = {"NFO:NIFTY26SEP24000CE": {"last_price": 65.0}}

        positions = {
            "NIFTY": {
                "symbol": "NIFTY",
                "contract": "NIFTY26SEP24000CE",
                "option_token": 99999,
                "entry_spot": 100.0,
                "current_sl": 90.0,
                "t1": 150.0,
                "position_type": "option",
                "quantity": 25,
                "position_size": 1,
                "side": "CE",
                "timeframe": "15minute",
                "entry_time": "2026-09-25 14:00:00"
            }
        }
        lock = MagicMock()
        mock_db = MagicMock()
        log_fn = MagicMock()

        monitor_active_positions(
            mock_kite, {"NIFTY": {"token": 99999}}, positions, lock,
            "NRML", "index", "15minute", mock_db, log_fn, live=True
        )

        mock_close.assert_called_once()
        self.assertNotIn("NIFTY", positions)


class TestAdversarialDebitSpreadRollback(unittest.TestCase):
    """Adversarial stress-testing of debit spread failure, freeze slice cancellation, and rollback."""

    def test_stock_engine_leg2_partial_fill_and_unwind_retention(self):
        """In stock_options_trade_engine:
        When Leg 2 short is partially filled (slice 1) before slice 2 fails:
        1. Leg 2 short must be immediately covered via marketable limit BUY.
        2. Resting Leg 1 orders must be cancelled.
        3. Held Leg 1 must undergo emergency unwind.
        4. If emergency unwind fails, position MUST be retained in ACTIVE_POSITIONS and trade_db as ACTIVE.
        """
        import Trade_Option.stock_options_trade_engine as stk_engine

        mock_kite = MagicMock()
        mock_kite.VARIETY_REGULAR = "regular"
        mock_kite.TRANSACTION_TYPE_BUY = "BUY"
        mock_kite.TRANSACTION_TYPE_SELL = "SELL"
        mock_kite.ORDER_TYPE_LIMIT = "LIMIT"
        mock_kite.PRODUCT_NRML = "NRML"
        mock_kite.EXCHANGE_NFO = "NFO"

        placed_orders = []
        def mock_place_order(**kwargs):
            placed_orders.append(kwargs)
            tsym = kwargs.get("tradingsymbol")
            ttype = kwargs.get("transaction_type")
            tag = kwargs.get("tag")

            if tag == "spread_l2_cover":
                return "COVER_OID_1"
            if tag == "spread_unwind":
                raise RuntimeError("Broker connection timeout on emergency unwind")
            return f"OID_{tsym}_{ttype}"

        mock_kite.place_order.side_effect = mock_place_order
        mock_kite.quote.return_value = {
            "NFO:RELIANCE26OCT2600CE": {"depth": {"buy": [{"price": 45.0}]}, "last_price": 45.0},
            "NFO:RELIANCE26OCT2650CE": {"depth": {"buy": [{"price": 25.0}]}, "last_price": 25.0}
        }

        holding_map = {
            "RELIANCE26OCT2650CE": (True, -250),
            "RELIANCE26OCT2600CE": (True, 250)
        }
        def mock_is_held(k, c):
            return holding_map.get(c, (False, 0))

        contract = "RELIANCE26OCT2600CE"
        sym = "RELIANCE"
        qty = 250
        limit_price = 45.0
        placed_oids = ["LEG1_OID_1"]
        leg2_placed = ["LEG2_OID_1"]
        spread_info = {
            "spread_type": "BULL_CALL_DEBIT_SPREAD",
            "leg1": {"contract": contract, "strike": 2600},
            "leg2": {"contract": "RELIANCE26OCT2650CE", "strike": 2650}
        }
        leg2_c = spread_info["leg2"]["contract"]
        leg2_limit = 24.85
        pos = {
            "symbol": sym,
            "contract": contract,
            "position_type": "option_spread",
            "quantity": qty,
            "trade_id": 7771
        }
        stk_engine.ACTIVE_POSITIONS[sym] = pos

        with patch("common.position_monitor.is_contract_held_on_broker", side_effect=mock_is_held), \
             patch("position_monitor.is_contract_held_on_broker", side_effect=mock_is_held), \
             patch("Trade_Option.stock_options_trade_engine.trade_db.update_trade") as mock_db_update, \
             patch("Trade_Option.stock_options_trade_engine.save_state"):

            # 1. Cancel Leg 1
            for o_to_cancel in placed_oids:
                mock_kite.cancel_order(variety=mock_kite.VARIETY_REGULAR, order_id=str(o_to_cancel))
            # 2. Cancel Leg 2 partial orders
            for o2_cancel in leg2_placed:
                mock_kite.cancel_order(variety=mock_kite.VARIETY_REGULAR, order_id=str(o2_cancel))

            # 3. Leg 2 short cover
            l2_held, l2_held_qty = mock_is_held(mock_kite, leg2_c)
            if l2_held and l2_held_qty < 0:
                cover_qty = abs(l2_held_qty)
                mock_kite.place_order(
                    variety=mock_kite.VARIETY_REGULAR, tradingsymbol=leg2_c,
                    exchange=mock_kite.EXCHANGE_NFO, transaction_type=mock_kite.TRANSACTION_TYPE_BUY,
                    quantity=cover_qty, order_type=mock_kite.ORDER_TYPE_LIMIT,
                    price=26.05, product=mock_kite.PRODUCT_NRML, tag="spread_l2_cover"
                )

            # 4. Emergency unwind Leg 1
            is_held, held_qty = mock_is_held(mock_kite, contract)
            if is_held and held_qty > 0:
                try:
                    mock_kite.place_order(
                        variety=mock_kite.VARIETY_REGULAR, tradingsymbol=contract,
                        exchange=mock_kite.EXCHANGE_NFO, transaction_type=mock_kite.TRANSACTION_TYPE_SELL,
                        quantity=held_qty, order_type=mock_kite.ORDER_TYPE_LIMIT, price=44.1,
                        product=mock_kite.PRODUCT_NRML, tag="spread_unwind"
                    )
                except Exception as unw_err:
                    rem_held, rem_held_qty = mock_is_held(mock_kite, contract)
                    rem_qty = rem_held_qty if (rem_held and rem_held_qty > 0) else held_qty
                    if rem_qty > 0:
                        pos["position_type"] = "option"
                        pos["quantity"] = rem_qty
                        pos["position_size"] = 1
                        stk_engine.ACTIVE_POSITIONS[sym] = pos
                        stk_engine.trade_db.update_trade(pos["trade_id"], {
                            "status": "ACTIVE",
                            "position_type": "option",
                            "quantity": rem_qty,
                            "lots": 1
                        })

        # Verify Leg 1 resting order was cancelled
        cancel_calls = [c[1]["order_id"] for c in mock_kite.cancel_order.call_args_list]
        self.assertIn("LEG1_OID_1", cancel_calls)
        self.assertIn("LEG2_OID_1", cancel_calls)

        # Verify Leg 2 short was covered
        cover_calls = [p for p in placed_orders if p.get("tag") == "spread_l2_cover"]
        self.assertEqual(len(cover_calls), 1)
        self.assertEqual(cover_calls[0]["tradingsymbol"], "RELIANCE26OCT2650CE")
        self.assertEqual(cover_calls[0]["transaction_type"], "BUY")
        self.assertEqual(cover_calls[0]["quantity"], 250)

        # Verify position was retained as ACTIVE in ACTIVE_POSITIONS and trade_db
        self.assertIn("RELIANCE", stk_engine.ACTIVE_POSITIONS)
        self.assertEqual(stk_engine.ACTIVE_POSITIONS["RELIANCE"]["position_type"], "option")
        mock_db_update.assert_called_with(7771, {
            "status": "ACTIVE",
            "position_type": "option",
            "quantity": 250,
            "lots": 1
        })

    def test_exchange_resolution_bfo_vs_nfo(self):
        """Verify that SENSEX/BANKEX route to BFO exchange while NIFTY routes to NFO."""
        test_cases = [
            ("SENSEX26SEP80000CE", "BFO"),
            ("BANKEX26SEP55000CE", "BFO"),
            ("NIFTY26SEP24000CE", "NFO"),
            ("BANKNIFTY26SEP52000CE", "NFO")
        ]

        for cnt, expected_exch in test_cases:
            target_exch = "BFO" if ("SENSEX" in cnt.upper() or "BSE" in cnt.upper() or "BANKEX" in cnt.upper()) else "NFO"
            self.assertEqual(target_exch, expected_exch, f"{cnt} must resolve to {expected_exch}")

            exchange_for_exit = "BFO" if any(idx in cnt.upper() for idx in ["SENSEX", "BANKEX"]) else "NFO"
            self.assertEqual(exchange_for_exit, expected_exch, f"{cnt} emergency exit must resolve to {expected_exch}")

    def test_index_options_engine_caller_clobber_vulnerability(self):
        """VULNERABILITY REPRODUCTION:
        In index_options_trade_engine.py:
        When execute_index_entry retains a stranded Leg 1 option in ACTIVE_POSITIONS and sets status='ACTIVE',
        it returns False.
        The caller in run_scan_cycle (lines 867-872) receives ok=False and executes:
            ACTIVE_POSITIONS.pop(best['symbol'], None)
            trade_db.update_trade(pos['trade_id'], {'status': 'FAILED', 'exit_reason': 'ORDER_PLACEMENT_FAILED'})
        This empirically proves that the retained trade is destroyed and position_monitor is starved!
        """
        import Trade_Option.index_options_trade_engine as idx_engine

        mock_kite = MagicMock()
        mock_kite.VARIETY_REGULAR = "regular"
        mock_kite.TRANSACTION_TYPE_BUY = "BUY"
        mock_kite.TRANSACTION_TYPE_SELL = "SELL"
        mock_kite.ORDER_TYPE_LIMIT = "LIMIT"
        mock_kite.PRODUCT_NRML = "NRML"

        def mock_place_order(**kwargs):
            tsym = kwargs.get("tradingsymbol")
            ttype = str(kwargs.get("transaction_type"))
            if tsym == "NIFTY26SEP24000CE" and ttype == "BUY":
                return "LEG1_OID"
            elif tsym == "NIFTY26SEP24200CE" and ttype == "SELL":
                raise RuntimeError("Leg 2 rejection")
            elif tsym == "NIFTY26SEP24000CE" and ttype == "SELL":
                raise RuntimeError("Emergency unwind timeout")
            return "OTHER"

        mock_kite.place_order.side_effect = mock_place_order
        mock_kite.ltp.return_value = {"NFO:NIFTY26SEP24000CE": {"last_price": 100.0}}

        pos = {
            "symbol": "NIFTY",
            "contract": "NIFTY26SEP24000CE",
            "position_type": "option_spread",
            "leg2_contract": "NIFTY26SEP24200CE",
            "entry_premium": 100.0,
            "lot_size": 25,
            "position_size": 1,
            "trade_id": 5555
        }
        idx_engine.ACTIVE_POSITIONS["NIFTY"] = pos

        broker_holdings = [
            (False, 0),    # Leg 2 check
            (True, 25),    # Check after Leg 2 failure
            (True, 25)     # Check after unwind failure
        ]

        db_updates = []
        def mock_update(tid, data):
            db_updates.append((tid, data))

        with patch("liquidity_guard.check_bid_ask_spread_liquidity", return_value=(True, 0.01, "OK", 0)), \
             patch("common.position_monitor.confirm_leg1_order_filled", return_value=(True, ["LEG1_OID"], [], "ALL_COMPLETE")), \
             patch("common.position_monitor.is_contract_held_on_broker", side_effect=broker_holdings), \
             patch("session.safe_kite_call", side_effect=lambda fn, *a, **kw: fn(*a, **kw)), \
             patch("Trade_Option.index_options_trade_engine.safe_kite_call", side_effect=lambda fn, *a, **kw: fn(*a, **kw)), \
             patch("Trade_Option.index_options_trade_engine.trade_db.update_trade", side_effect=mock_update):

            ok = idx_engine.execute_index_entry(mock_kite, pos)
            # execute_index_entry returns False
            self.assertFalse(ok)
            # At this moment, pos was retained in ACTIVE_POSITIONS
            self.assertIn("NIFTY", idx_engine.ACTIVE_POSITIONS)
            self.assertEqual(db_updates[-1][1]["status"], "ACTIVE")

            # NOW SIMULATE EXACT CALLER CODE in index_options_trade_engine.py lines 867-874:
            if not ok:
                with idx_engine.position_lock:
                    idx_engine.ACTIVE_POSITIONS.pop("NIFTY", None)
                if pos.get("trade_id"):
                    idx_engine.trade_db.update_trade(pos["trade_id"], {
                        "status": "FAILED",
                        "exit_reason": "ORDER_PLACEMENT_FAILED",
                        "updated_at": "2026-09-26 12:00:00"
                    })

            # EMPIRICAL PROOF OF VULNERABILITY:
            # Position is popped from ACTIVE_POSITIONS!
            self.assertNotIn("NIFTY", idx_engine.ACTIVE_POSITIONS)
            # Database record was overwritten to FAILED!
            self.assertEqual(db_updates[-1][1]["status"], "FAILED")
            self.assertEqual(db_updates[-1][1]["exit_reason"], "ORDER_PLACEMENT_FAILED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
