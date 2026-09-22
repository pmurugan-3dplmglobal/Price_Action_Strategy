import sqlite3, json, csv, os, sys
sys.stdout.reconfigure(encoding='utf-8')

print("=== CHECKING trades.sqlite3 FOR EICHERMOT ===")
if os.path.exists("output/monitor/trades.sqlite3"):
    conn = sqlite3.connect("output/monitor/trades.sqlite3")
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(trades);")
    cols = [c[1] for c in cursor.fetchall()]
    cursor.execute("SELECT * FROM trades WHERE contract LIKE '%EICHERMOT%' OR symbol LIKE '%EICHERMOT%' ORDER BY id DESC LIMIT 5")
    rows = cursor.fetchall()
    for r in rows:
        d = dict(zip(cols, r))
        print("Trade ID:", d.get("id"), "Symbol:", d.get("symbol"), "Contract:", d.get("contract"), "Status:", d.get("status"))
        print("  Data JSON:", d.get("data_json"))
    conn.close()

print("\n=== CHECKING trade_journal.csv TODAY FOR EICHERMOT ===")
if os.path.exists("output/monitor/trade_journal.csv"):
    with open("output/monitor/trade_journal.csv", "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.reader(f, delimiter="\t")
        for row in reader:
            if len(row) > 0 and "2026-09-21" in row[0] and any("EICHERMOT" in str(x) for x in row):
                print(row)

print("\n=== CHECKING executed_exit_orders.json FOR EICHERMOT ===")
if os.path.exists("output/monitor/executed_exit_orders.json"):
    with open("output/monitor/executed_exit_orders.json", "r", encoding="utf-8") as f:
        d = json.load(f)
        for k, v in d.items():
            if "EICHERMOT" in str(k) or "EICHERMOT" in str(v):
                print(k, "->", v)
