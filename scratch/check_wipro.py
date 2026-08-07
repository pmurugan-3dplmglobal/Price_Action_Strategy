import json
import os
import csv
import sys
from datetime import datetime

COMMON_DIR = os.path.abspath("common")
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

from trading_core import load_kite_session, fetch_and_resample_candles
from kiteconnect import KiteConnect

print("=== EXECUTED EXITS ===")
p_exits = 'Trade_Option/output/monitor/executed_exit_orders.json'
if os.path.exists(p_exits):
    with open(p_exits) as f:
        ex = json.load(f)
    for k, v in ex.items():
        if 'WIPRO' in k.upper():
            print(k, json.dumps(v, indent=2))

print("\n=== TRADES DB (ALL WIPRO TRADES) ===")
p_trades = 'Trade_Option/output/monitor/trades_db.json'
wipro_trades = []
if os.path.exists(p_trades):
    with open(p_trades) as f:
        tr = json.load(f)
    for t in tr.get('trades', []):
        if 'WIPRO' in str(t.get('contract', '')).upper() or 'WIPRO' in str(t.get('symbol', '')).upper():
            wipro_trades.append(t)
            print(json.dumps(t, indent=2))

print("\n=== DAILY TRADE JOURNAL (WIPRO) ===")
p_j_csv = 'Trade_Option/output/daily_trade_journal.csv'
if os.path.exists(p_j_csv):
    with open(p_j_csv) as f:
        reader = csv.reader(f)
        for row in reader:
            if any('WIPRO' in cell.upper() for cell in row):
                print(row)

print("\n=== LIVE QUOTES FOR WIPRO CONTRACTS ===")
try:
    api_k, acc_t = load_kite_session()
    kite = KiteConnect(api_key=api_k, access_token=acc_t)
    q = kite.quote(['NFO:WIPRO26AUG200CE', 'NFO:WIPRO26AUG185PE', 'NSE:WIPRO'])
    print(json.dumps(q, indent=2, default=str))
except Exception as e:
    print(f"Kite quote fetch error: {e}")
