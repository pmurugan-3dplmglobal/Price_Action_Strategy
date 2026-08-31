import os
import sys
import json
import sqlite3

_COMMON_DIR = os.path.join(os.getcwd(), "common")
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)

import paths
import trade_db

# 1. Update sl_target_overrides.json
ov_file = paths.SL_TARGET_OVERRIDES_FILE
with open(ov_file, "r") as f:
    overrides = json.load(f)

overrides.setdefault("nifty50", {})
overrides["nifty50"]["TATAPOWER26SEP350CE"] = {
    "current_sl": 7.20,
    "t1": 20.10,
    "t2": 29.20,
    "t3": 30.50,
    "user_edited": True
}

with open(ov_file, "w") as f:
    json.dump(overrides, f, indent=2)
print("Updated sl_target_overrides.json with TATAPOWER SL = 7.20")

# 2. Update SQLite trade
db_path = os.path.join("output", "monitor", "trades.sqlite3")
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("SELECT id, data_json FROM trades WHERE contract LIKE '%TATAPOWER26SEP350CE%' AND status = 'ACTIVE' ORDER BY id DESC LIMIT 1")
row = cur.fetchone()
if row:
    tid = row[0]
    dj = json.loads(row[1])
    dj["entry_spot"] = 8.40
    dj["current_sl"] = 7.20
    dj["t1"] = 20.10
    dj["t2"] = 29.20
    dj["t3"] = 30.50
    cur.execute("UPDATE trades SET data_json = ? WHERE id = ?", (json.dumps(dj), tid))
    conn.commit()
    print(f"Updated SQLite trade ID {tid} with entry = 8.40, SL = 7.20")
conn.close()
