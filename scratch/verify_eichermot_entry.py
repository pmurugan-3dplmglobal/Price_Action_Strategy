import sqlite3, json
from datetime import datetime as dt
from common.position_monitor import is_candle_before_entry, sanitize_entry_time

conn = sqlite3.connect("output/monitor/trades.sqlite3")
cursor = conn.cursor()
cursor.execute("SELECT data_json FROM trades WHERE id = 676")
row = cursor.fetchone()
pos = json.loads(row[0])
conn.close()

entry_time_str = sanitize_entry_time(pos)
print("Trade 676 entry_time_str:", entry_time_str)
print("Trade 676 entry_spot / entry_price:", pos.get("entry_spot"), pos.get("entry_price"))

print("Is 2026-09-21 09:18:00 before entry?", is_candle_before_entry("2026-09-21 09:18:00", entry_time_str))
print("Is 2026-09-21 09:52:10 before entry?", is_candle_before_entry("2026-09-21 09:52:10", entry_time_str))
