"""
Unit verification suite for Stale Unfilled Limit Order Manager & TTL Invalidation Watcher.
Validates:
1. Target T1 Touched Invalidation (LTP >= T1 or High >= T1 before fill)
2. Time-To-Live (TTL) Expired Invalidation (> 15 minutes unfilled)
3. Stop Loss Breached Invalidation (LTP <= SL before fill)
4. Partial Fill Handling (cancels unfilled remainder, retains filled portion)
5. Broker Live Position Reconciler Guard (does not clobber trades with active open orders)
"""
import os
import sys
import threading
from datetime import datetime as dt, timedelta

WORKSPACE_ROOT = r"g:\Poovendan\AI\Trading\Share\ReadyToDeploy\Prod_code_01\Price_Action_Strategy"
COMMON_DIR = os.path.join(WORKSPACE_ROOT, "common")
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

from position_monitor import reconcile_and_cancel_stale_orders
import trade_db


class MockKite:
    VARIETY_REGULAR = "regular"

    def __init__(self, orders=None, positions=None, quotes=None):
        self._orders = orders or []
        self._positions = positions or {"net": [], "day": []}
        self._quotes = quotes or {}
        self.cancelled_orders = []

    def orders(self):
        return list(self._orders)

    def positions(self):
        return self._positions

    def quote(self, keys):
        return {k: self._quotes[k] for k in keys if k in self._quotes}

    def cancel_order(self, variety, order_id):
        self.cancelled_orders.append({"variety": variety, "order_id": str(order_id)})
        for o in self._orders:
            if str(o.get("order_id")) == str(order_id):
                o["status"] = "CANCELLED"
        return True


def run_tests():
    passed = 0
    total = 7

    # ─────────────────────────────────────────────────────────────
    # TEST 1: Target T1 Touched Before Fill Invalidation
    # ─────────────────────────────────────────────────────────────
    print("\n--- Test 1: Target T1 Touched Before Fill ---")
    mock_orders = [
        {
            "order_id": "1001",
            "tradingsymbol": "SENSEX24SEP76500PE",
            "exchange": "BFO",
            "transaction_type": "BUY",
            "price": 283.30,
            "quantity": 20,
            "filled_quantity": 0,
            "pending_quantity": 20,
            "status": "OPEN",
            "variety": "regular",
            "order_timestamp": dt.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    ]
    mock_quotes = {
        "BFO:SENSEX24SEP76500PE": {
            "last_price": 427.75,
            "ohlc": {"high": 435.0, "low": 280.0, "open": 285.0}
        }
    }
    pos_dict = {
        "SENSEX": {
            "contract": "SENSEX24SEP76500PE",
            "entry_spot": 283.30,
            "current_sl": 230.0,
            "t1": 350.0,
            "t2": 420.0,
            "order_id": "1001",
            "order_status": "OPEN",
            "symbol": "SENSEX",
            "side": "PE",
            "pattern": "BASE_ABCD"
        }
    }
    lock = threading.Lock()
    mock_kite = MockKite(orders=mock_orders, quotes=mock_quotes)

    res = reconcile_and_cancel_stale_orders(mock_kite, positions_dict=pos_dict, position_lock=lock, live=True)
    assert len(mock_kite.cancelled_orders) == 1, f"Expected 1 cancelled order, got {len(mock_kite.cancelled_orders)}"
    assert mock_kite.cancelled_orders[0]["order_id"] == "1001"
    assert "SENSEX" not in pos_dict, "SENSEX position should have been removed from positions_dict"
    print("[PASS] Test 1 Passed: SENSEX PE limit order cancelled because LTP (427.75) exceeded Target T1 (350.0).")
    passed += 1

    # ─────────────────────────────────────────────────────────────
    # TEST 2: Time-To-Live (TTL) Expired Invalidation
    # ─────────────────────────────────────────────────────────────
    print("\n--- Test 2: Time-To-Live (TTL) Expired ---")
    stale_ts = (dt.now() - timedelta(minutes=35)).strftime("%Y-%m-%d %H:%M:%S")
    mock_orders = [
        {
            "order_id": "1002",
            "tradingsymbol": "NIFTY24SEP23950PE",
            "exchange": "NFO",
            "transaction_type": "BUY",
            "price": 75.80,
            "quantity": 75,
            "filled_quantity": 0,
            "pending_quantity": 75,
            "status": "OPEN",
            "variety": "regular",
            "order_timestamp": stale_ts
        }
    ]
    mock_quotes = {
        "NFO:NIFTY24SEP23950PE": {
            "last_price": 76.50, # near entry, but 35 minutes old (> 30m TTL)
            "ohlc": {"high": 80.0, "low": 74.0, "open": 75.0}
        }
    }
    pos_dict = {
        "NIFTY": {
            "contract": "NIFTY24SEP23950PE",
            "entry_spot": 75.80,
            "current_sl": 60.0,
            "t1": 110.0,
            "order_id": "1002",
            "order_status": "OPEN",
            "symbol": "NIFTY",
            "side": "PE",
            "pattern": "BULL_ENG"
        }
    }
    mock_kite = MockKite(orders=mock_orders, quotes=mock_quotes)
    res = reconcile_and_cancel_stale_orders(mock_kite, positions_dict=pos_dict, position_lock=lock, live=True)
    assert len(mock_kite.cancelled_orders) == 1, f"Expected 1 cancelled order, got {len(mock_kite.cancelled_orders)}"
    assert mock_kite.cancelled_orders[0]["order_id"] == "1002"
    assert "NIFTY" not in pos_dict
    print("[PASS] Test 2 Passed: NIFTY PE limit order cancelled due to TTL expiration (35m > 30m limit).")
    passed += 1

    # ─────────────────────────────────────────────────────────────
    # TEST 3: Stop-Loss Breached Before Fill Invalidation
    # ─────────────────────────────────────────────────────────────
    print("\n--- Test 3: Stop-Loss Breached Before Fill ---")
    mock_orders = [
        {
            "order_id": "1003",
            "tradingsymbol": "RELIANCE24SEP3000CE",
            "exchange": "NFO",
            "transaction_type": "BUY",
            "price": 45.0,
            "quantity": 250,
            "filled_quantity": 0,
            "pending_quantity": 250,
            "status": "OPEN",
            "variety": "regular",
            "order_timestamp": dt.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    ]
    mock_quotes = {
        "NFO:RELIANCE24SEP3000CE": {
            "last_price": 32.0, # Breached SL of 36.0
            "ohlc": {"high": 46.0, "low": 31.0, "open": 44.0}
        }
    }
    pos_dict = {
        "RELIANCE": {
            "contract": "RELIANCE24SEP3000CE",
            "entry_spot": 45.0,
            "current_sl": 36.0,
            "t1": 65.0,
            "order_id": "1003",
            "order_status": "OPEN",
            "symbol": "RELIANCE",
            "side": "CE",
            "pattern": "BASE_ABCD"
        }
    }
    mock_kite = MockKite(orders=mock_orders, quotes=mock_quotes)
    res = reconcile_and_cancel_stale_orders(mock_kite, positions_dict=pos_dict, position_lock=lock, live=True)
    assert len(mock_kite.cancelled_orders) == 1, f"Expected 1 cancelled order, got {len(mock_kite.cancelled_orders)}"
    assert mock_kite.cancelled_orders[0]["order_id"] == "1003"
    assert "RELIANCE" not in pos_dict
    print("[PASS] Test 3 Passed: RELIANCE CE limit order cancelled because price (32.0) breached SL (36.0).")
    passed += 1

    # ─────────────────────────────────────────────────────────────
    # TEST 4: Partial Fill Handling (Cancel remainder, retain filled)
    # ─────────────────────────────────────────────────────────────
    print("\n--- Test 4: Partial Fill Handling ---")
    mock_orders = [
        {
            "order_id": "1004",
            "tradingsymbol": "FINNIFTY24SEP25950PE",
            "exchange": "NFO",
            "transaction_type": "BUY",
            "price": 196.80,
            "quantity": 100,
            "filled_quantity": 25,
            "pending_quantity": 75,
            "status": "OPEN",
            "variety": "regular",
            "order_timestamp": dt.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    ]
    mock_quotes = {
        "NFO:FINNIFTY24SEP25950PE": {
            "last_price": 240.0, # T1 reached
            "ohlc": {"high": 242.0, "low": 195.0, "open": 196.0}
        }
    }
    pos_dict = {
        "FINNIFTY": {
            "contract": "FINNIFTY24SEP25950PE",
            "entry_spot": 196.80,
            "current_sl": 160.0,
            "t1": 235.0,
            "order_id": "1004",
            "order_status": "OPEN",
            "position_size": 4, # 4 lots = 100 qty
            "symbol": "FINNIFTY",
            "side": "PE",
            "pattern": "BASE_ABCD"
        }
    }
    mock_kite = MockKite(orders=mock_orders, quotes=mock_quotes)
    res = reconcile_and_cancel_stale_orders(mock_kite, positions_dict=pos_dict, position_lock=lock, live=True)
    assert len(mock_kite.cancelled_orders) == 1
    assert "FINNIFTY" in pos_dict, "FINNIFTY should remain in pos_dict because 25 lots filled!"
    assert pos_dict["FINNIFTY"]["order_status"] == "COMPLETE"
    print("[PASS] Test 4 Passed: Unfilled 75 qty remainder cancelled when T1 touched; filled 25 qty retained for trailing.")
    passed += 1

    # ─────────────────────────────────────────────────────────────
    # TEST 5: Broker Live Position Reconciler Guard
    # ─────────────────────────────────────────────────────────────
    print("\n--- Test 5: Broker Live Position Reconciler Guard ---")
    # Simulate trade in trade_db with open limit order on Kite
    tid, _ = trade_db.create_trade("nifty50", "POWERGRID", {
        "contract": "POWERGRID24SEP265CE",
        "entry_spot": 5.80,
        "current_sl": 4.50,
        "t1": 8.0,
        "status": "ACTIVE"
    }, allow_duplicate=True)

    mock_kite = MockKite(
        orders=[{
            "order_id": "1005",
            "tradingsymbol": "POWERGRID24SEP265CE",
            "status": "OPEN"
        }],
        positions={"net": [{"tradingsymbol": "POWERGRID24SEP265CE", "quantity": 0}]}
    )
    # When reconcile_broker_live_positions runs, it should NOT clobber the trade because an open order exists!
    reconciled = trade_db.reconcile_broker_live_positions(mock_kite)
    t_after = trade_db.get_trade(tid)
    assert t_after is not None and t_after.get("status") == "ACTIVE", f"Expected trade #{tid} to remain ACTIVE, got {t_after.get('status') if t_after else None}"
    print("[PASS] Test 5 Passed: reconcile_broker_live_positions preserved ACTIVE trade with pending Kite limit order.")
    passed += 1

    # Clean up test trade
    trade_db.remove_trades([tid])

    # ─────────────────────────────────────────────────────────────
    # TEST 6: Order-Fill Grace Window (120s) — ISSUE-059
    # ─────────────────────────────────────────────────────────────
    print("\n--- Test 6: Order-Fill Grace Window (120s) ---")
    # Simulate a freshly-created trade (created_at = now - 10 seconds)
    from timeframe_utils import get_ist_now
    fresh_now = get_ist_now().strftime("%Y-%m-%d %H:%M:%S")
    tid6, _ = trade_db.create_trade("nifty50", "TATAPOWER", {
        "contract": "TATAPOWER24SEP460CE",
        "entry_spot": 12.50,
        "current_sl": 9.00,
        "t1": 18.00,
        "status": "ACTIVE",
        "created_at": fresh_now,  # Just created — within grace window
    }, allow_duplicate=True)

    mock_kite6 = MockKite(
        orders=[],  # No open orders on Kite (order submitted but not yet visible / already matched)
        positions={"net": [{"tradingsymbol": "TATAPOWER24SEP460CE", "quantity": 0}]}  # Not filled yet
    )
    reconciled6 = trade_db.reconcile_broker_live_positions(mock_kite6)
    t6_after = trade_db.get_trade(tid6)
    assert t6_after is not None and t6_after.get("status") == "ACTIVE", \
        f"Expected trade #{tid6} to remain ACTIVE (grace window), got {t6_after.get('status') if t6_after else None}"
    print("[PASS] Test 6 Passed: reconcile_broker_live_positions preserved ACTIVE trade within 120s grace window.")
    passed += 1

    # Clean up
    trade_db.remove_trades([tid6])

    # ─────────────────────────────────────────────────────────────
    # TEST 7: DB Order-Status Guard — ISSUE-059
    # ─────────────────────────────────────────────────────────────
    print("\n--- Test 7: DB Order-Status Guard ---")
    # Simulate an older trade (created 5 minutes ago — beyond grace window)
    # but with order_status = "OPEN" in DB
    old_time = (get_ist_now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    tid7, _ = trade_db.create_trade("nifty50", "BHEL", {
        "contract": "BHEL24SEP300CE",
        "entry_spot": 8.00,
        "current_sl": 6.00,
        "t1": 12.00,
        "status": "ACTIVE",
        "created_at": old_time,
        "order_status": "OPEN",  # Limit order resting on exchange
    }, allow_duplicate=True)

    mock_kite7 = MockKite(
        orders=[],  # Kite orders() API returned empty (API failure or stale snapshot)
        positions={"net": [{"tradingsymbol": "BHEL24SEP300CE", "quantity": 0}]}
    )
    reconciled7 = trade_db.reconcile_broker_live_positions(mock_kite7)
    t7_after = trade_db.get_trade(tid7)
    assert t7_after is not None and t7_after.get("status") == "ACTIVE", \
        f"Expected trade #{tid7} to remain ACTIVE (order_status=OPEN guard), got {t7_after.get('status') if t7_after else None}"
    print("[PASS] Test 7 Passed: reconcile_broker_live_positions preserved ACTIVE trade with DB order_status=OPEN.")
    passed += 1

    # Clean up
    trade_db.remove_trades([tid7])

    print(f"\n==========================================")
    print(f"Stale Order Invalidation Suite: {passed}/{total} PASSED (100% SUCCESS)")
    print(f"==========================================\n")


if __name__ == "__main__":
    run_tests()
