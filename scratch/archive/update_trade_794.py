import sqlite3, json

conn = sqlite3.connect("output/monitor/trades.sqlite3")
row = conn.execute("SELECT data_json FROM trades WHERE id = 794").fetchone()
if row:
    d = json.loads(row[0])
    d["status"] = "CLOSED"
    d["exit_price"] = 0.83
    d["exit_reason"] = "MANUAL_DEBIT_SPREAD_ORPHAN_SQUAREOFF"
    conn.execute(
        "UPDATE trades SET status = 'CLOSED', data_json = ?, updated_at = datetime('now', 'localtime') WHERE id = 794",
        (json.dumps(d),)
    )
    conn.commit()
    print("Trade 794 successfully updated to CLOSED in SQLite DB.")
