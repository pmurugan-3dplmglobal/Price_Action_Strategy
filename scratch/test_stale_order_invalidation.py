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
    total = 5

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

    print(f"\n==========================================")
    print(f"Stale Order Invalidation Suite: {passed}/{total} PASSED (100% SUCCESS)")
    print(f"==========================================\n")


if __name__ == "__main__":
    run_tests()
