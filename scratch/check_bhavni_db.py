import json
import sqlite3
import os

monitor = "/home/trade/Trade_Kite/Price_Action_Strategy/output/monitor"

print("=== EXECUTED EXIT ORDERS ===")
exit_file = os.path.join(monitor, "executed_exit_orders.json")
if os.path.exists(exit_file):
    with open(exit_file) as f:
        print(json.dumps(json.load(f), indent=2))

print("\n=== EXECUTED PATTERNS ===")
pat_file = os.path.join(monitor, "executed_patterns.json")
if os.path.exists(pat_file):
    with open(pat_file) as f:
        print(json.dumps(json.load(f), indent=2))

print("\n=== TRADES SQLITE ===")
db_file = os.path.join(monitor, "trades.sqlite3")
if os.path.exists(db_file):
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT id, symbol, contract, entry_price, current_sl, t1, status, exit_price, exit_reason, pnl, entry_time, exit_time FROM trades ORDER BY id DESC LIMIT 10")
    for r in c.fetchall():
        print(dict(r))
