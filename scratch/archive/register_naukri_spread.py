import sys
import json
import sqlite3
sys.path.insert(0, 'common')
from trading_core import load_kite_session
from kiteconnect import KiteConnect
import trade_db
import paths

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

# 1. Fetch quote for Leg 1 and Leg 2
q = kite.quote(['NFO:NAUKRI26SEP1300PE', 'NFO:NAUKRI26SEP1260PE', 'NSE:NAUKRI'])
leg1_q = q.get('NFO:NAUKRI26SEP1300PE', {})
leg2_q = q.get('NFO:NAUKRI26SEP1260PE', {})
spot_q = q.get('NSE:NAUKRI', {})

print("Leg 1 Token:", leg1_q.get('instrument_token'))
print("Leg 2 Token:", leg2_q.get('instrument_token'))

# Check existing NAUKRI trades
conn = sqlite3.connect(r"output/monitor/trades.sqlite3")
cur = conn.cursor()
cur.execute("SELECT id, engine, symbol, contract, status FROM trades WHERE symbol='NAUKRI'")
rows = cur.fetchall()
print("Existing NAUKRI trades in DB:", rows)

# Create or update trade in trade_db
spread_trade = {
    "contract": "NAUKRI26SEP1300PE",
    "option_token": leg1_q.get('instrument_token'),
    "entry_spot": 14.80,
    "current_sl": 6.00,  # Spread SL floor (max spread loss ~5.65 pts)
    "t1": 25.00,
    "t2": 32.00,
    "t3": 40.00,
    "trailing_stage": 0,
    "lot_size": 550,
    "position_size": 1,
    "pattern": "BEAR_PUT_SPREAD",
    "timeframe": "15minute",
    "side": "PE",
    "strike": 1300.0,
    "benchmark": 14.80,
    "direction": "BEAR",
    "spot_token": spot_q.get('instrument_token'),
    "spot_sl": 1323.48,
    "position_type": "option_spread",
    "spread_type": "BEAR_PUT_SPREAD",
    "leg2_contract": "NAUKRI26SEP1260PE",
    "leg2_token": leg2_q.get('instrument_token'),
    "leg2_strike": 1260.0,
    "leg2_qty": 550,
    "leg2_entry": 3.15,
    "leg2_order_id": "260922191137174",
    "order_id": "260922191079317",
    "order_status": "COMPLETE",
    "tier": 1,
    "tier_label": "TIER_1_GOLD",
    "tier_badge": "🥇 T1"
}

trade_id, created = trade_db.create_trade("nifty50", "NAUKRI", spread_trade)
print(f"Registered Trade ID: {trade_id} (Created: {created})")

# Ensure status is ACTIVE
trade_db.update_trade(trade_id, {"status": "ACTIVE"})
print(f"Trade {trade_id} set to ACTIVE status.")
conn.close()
