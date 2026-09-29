import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import sqlite3
import json
from common.paths import monitor_file

db_path = monitor_file("trades.sqlite3")
conn = sqlite3.connect(db_path)
c = conn.cursor()
c.execute("SELECT id, symbol, contract, status, data_json FROM trades WHERE id=1178")
row = c.fetchone()
if row:
    print(f"ID: {row[0]}, Sym: {row[1]}, Contract: {row[2]}, Status: {row[3]}")
    try:
        dj = json.loads(row[4])
        print("Data JSON keys:", list(dj.keys()))
        print("Order IDs:", dj.get("order_id"), dj.get("entry_order_id"), dj.get("leg1_order_id"), dj.get("leg2_order_id"))
        print("Status in data_json:", dj.get("status"))
    except Exception as e:
        print("Error parsing data_json:", e)

conn.close()
