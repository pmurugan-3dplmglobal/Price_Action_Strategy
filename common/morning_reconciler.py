"""
common/morning_reconciler.py
============================
Automated Market Open Pre-Flight Reconciler (09:16 AM IST).

Executes every trading day at 09:16 AM IST (1 minute after opening bell):
1. Reconciles Kite broker net positions vs SQLite trade_db.
2. Audits overnight price gaps against Stop Loss and Target T1.
   - Gap-Down Breach: Triggers immediate graceful exit.
   - Gap-Up Windfall: Automatically ratchets trailing stop to Trail 1 (Break-Even).
3. Verifies account margin health.
4. Writes status report to output/monitor/preflight_status.json and logs to trade journal.
"""

import os
import json
import logging
from datetime import datetime, time as datetime_time
import pandas as pd

try:
    import paths
    from session import load_kite_session, safe_kite_call
    from position_monitor import is_market_open, close_position, close_stock_position
    import trade_db
except ImportError:
    from common import paths
    from common.session import load_kite_session, safe_kite_call
    from common.position_monitor import is_market_open, close_position, close_stock_position
    from common import trade_db

PREFLIGHT_STATUS_FILE = os.path.join(paths.MONITOR_DIR, "preflight_status.json")


def is_preflight_window() -> bool:
    """Check if current time is within or past the 09:16 AM morning check window."""
    now = datetime.now()
    if now.weekday() >= 5:  # Saturday or Sunday
        return False
    current_time = now.time()
    return current_time >= datetime_time(9, 16) and current_time <= datetime_time(15, 30)


def run_preflight_reconciliation(kite=None, engines=("nifty50", "index", "daily", "bear_trade")):
    """
    Executes the 09:16 AM pre-flight audit.
    Can be invoked by daemons or run standalone.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().isoformat()
    logging.info("=" * 70)
    logging.info(f"[09:16 PRE-FLIGHT] Starting Morning State Audit for {today_str}...")
    logging.info("=" * 70)

    # 1. Initialize Kite Session if not provided
    if kite is None:
        try:
            from kiteconnect import KiteConnect
            api_k, acc_t = load_kite_session(paths.TOKEN_FILE)
            kite = KiteConnect(api_key=api_k)
            kite.set_access_token(acc_t)
        except Exception as k_err:
            logging.error(f"[09:16 PRE-FLIGHT] Kite session unavailable: {k_err}")
            return {
                "timestamp": now_str,
                "date": today_str,
                "status": "FAILED",
                "error": str(k_err)
            }

    report = {
        "timestamp": now_str,
        "date": today_str,
        "status": "IN_PROGRESS",
        "broker_positions": {},
        "db_active_positions": {},
        "discrepancies": [],
        "gap_events": [],
        "margin_summary": {},
        "summary": ""
    }

    # 2. Fetch Broker Positions
    kite_positions = {}
    try:
        broker_res = kite.positions()
        for p in broker_res.get("net", []):
            qty = int(p.get("quantity", 0))
            if qty != 0:
                sym = p.get("tradingsymbol", "")
                kite_positions[sym] = {
                    "quantity": qty,
                    "product": p.get("product"),
                    "pnl": float(p.get("pnl", 0.0)),
                    "exchange": p.get("exchange")
                }
        report["broker_positions"] = kite_positions
    except Exception as pos_err:
        logging.warning(f"[09:16 PRE-FLIGHT] Could not fetch broker net positions: {pos_err}")
        report["discrepancies"].append(f"Broker position query failed: {pos_err}")

    # 3. Audit Each Configured Engine in trade_db
    total_db_active = 0
    for eng in engines:
        active_trades = trade_db.get_active_trades(eng)
        total_db_active += len(active_trades)
        report["db_active_positions"][eng] = len(active_trades)

        for trade in active_trades:
            tid = trade.get("id")
            sym = trade.get("symbol", "")
            contract = trade.get("contract") or sym
            pos_type = trade.get("position_type", "option")
            sl_val = float(trade.get("current_sl") or 0.0)
            t1_val = float(trade.get("t1") or 0.0)
            entry_spot = float(trade.get("entry_spot") or trade.get("entry_price") or 0.0)
            side = str(trade.get("side", "BUY")).upper()
            is_bull = side in ["BUY", "CE", "BULL"]

            # Check A: Exists in DB but closed on Broker
            if contract not in kite_positions and is_market_open():
                disc_msg = f"Trade #{tid} ({contract}) active in DB but 0 quantity on broker."
                logging.warning(f"[09:16 PRE-FLIGHT MISMATCH] {disc_msg}")
                report["discrepancies"].append(disc_msg)
                trade_db.update_trade_status(tid, "CLOSED_EXTERNALLY", details="Zero quantity in broker net positions at 09:16 pre-flight")
                continue

            # Check B: Overnight Opening Gap Audit
            try:
                c_str = str(contract).upper()
                target_exch = "BFO" if ("SENSEX" in c_str or "BSE" in c_str) else ("NFO" if ("CE" in c_str or "PE" in c_str) else "NSE")
                q_key = f"{target_exch}:{contract}"
                q = kite.quote([q_key])
                if q_key in q:
                    ltp = float(q[q_key].get("last_price") or 0.0)
                    open_price = float(q[q_key].get("ohlc", {}).get("open") or ltp)

                    # Gap-Down Breach: Market opened below SL
                    if is_bull and sl_val > 0 and (ltp <= sl_val or open_price <= sl_val):
                        gap_msg = f"[GAP DOWN BREACH] {contract} opened at {open_price} (LTP={ltp}) below SL {sl_val}."
                        logging.warning(f"[09:16 PRE-FLIGHT] {gap_msg}")
                        report["gap_events"].append(gap_msg)
                        # Trigger controlled graceful exit
                        if pos_type == "stock":
                            close_stock_position(kite, trade, live_market=True)
                        else:
                            close_position(kite, trade, live_market=True)
                        trade_db.update_trade_status(tid, "SL_HIT", exit_price=ltp, exit_reason="OPENING_GAP_DOWN_BREACH")

                    # Gap-Up Windfall: Market opened past Target T1
                    elif is_bull and t1_val > 0 and (ltp >= t1_val or open_price >= t1_val):
                        if int(trade.get("trailing_stage") or 0) == 0:
                            gap_msg = f"[GAP UP WINDFALL] {contract} opened at {open_price} past Target T1 {t1_val}. Ratcheting SL to BE."
                            logging.info(f"[09:16 PRE-FLIGHT] {gap_msg}")
                            report["gap_events"].append(gap_msg)
                            new_sl = max(sl_val, entry_spot)
                            trade_db.update_trade(tid, {
                                "trailing_stage": 1,
                                "current_sl": new_sl,
                                "sl_set_time": now_str
                            })
            except Exception as q_err:
                logging.warning(f"[09:16 PRE-FLIGHT] Could not audit quote for {contract}: {q_err}")

    # 4. Account Margin Verification
    try:
        m_res = kite.margins(segment="equity")
        report["margin_summary"] = {
            "net": float(m_res.get("net", 0.0)),
            "available_cash": float(m_res.get("available", {}).get("cash", 0.0)),
            "collateral": float(m_res.get("available", {}).get("collateral", 0.0))
        }
        logging.info(f"[09:16 PRE-FLIGHT] Margin available: ₹{report['margin_summary']['available_cash']:,.2f}")
    except Exception as m_err:
        logging.warning(f"[09:16 PRE-FLIGHT] Margin check warning: {m_err}")

    # 5. Summarize and Save Status
    status_summary = (
        f"09:16 AM Pre-Flight completed: {len(kite_positions)} open broker positions, "
        f"{total_db_active} active DB trades, {len(report['gap_events'])} gap adjustments, "
        f"{len(report['discrepancies'])} discrepancies."
    )
    report["status"] = "SUCCESS" if not report["discrepancies"] else "WARNING"
    report["summary"] = status_summary
    logging.info(f"[09:16 PRE-FLIGHT] {status_summary}")

    try:
        os.makedirs(os.path.dirname(PREFLIGHT_STATUS_FILE), exist_ok=True)
        with open(PREFLIGHT_STATUS_FILE, "w", encoding="utf-8") as pf:
            json.dump(report, pf, indent=2)
    except Exception as save_err:
        logging.warning(f"Could not save {PREFLIGHT_STATUS_FILE}: {save_err}")

    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_preflight_reconciliation()
