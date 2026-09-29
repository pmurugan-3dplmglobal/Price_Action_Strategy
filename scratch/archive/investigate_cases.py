import json
import sqlite3
import os
import glob

print("=== 1. TRADES IN TRADES.SQLITE3 FOR TODAY (2026-09-29) ===")
conn = sqlite3.connect("output/monitor/trades.sqlite3")
c = conn.cursor()
c.execute("SELECT id, engine, symbol, contract, status, created_at, updated_at, data_json FROM trades WHERE created_at LIKE '2026-09-29%' ORDER BY id ASC")
rows = c.fetchall()
print(f"Total trades today in trades.sqlite3: {len(rows)}")
for r in rows:
    data = json.loads(r[7]) if r[7] else {}
    print(f"ID={r[0]} | Eng={r[1]} | Sym={r[2]} | Cnt={r[3]} | Stat={r[4]} | Created={r[5]} | Upd={r[6]} | PnL={data.get('pnl')} | ExitReason={data.get('exit_reason')} | Entry={data.get('entry_price')} | Exit={data.get('exit_price')}")
conn.close()

print("\n=== 2. EXECUTED PATTERNS JSON ===")
if os.path.exists("output/monitor/executed_patterns.json"):
    with open("output/monitor/executed_patterns.json", "r", encoding="utf-8") as f:
        ep = json.load(f)
    print(f"Total executed patterns: {len(ep)}")
    for k, v in list(ep.items())[-15:]:
        print(f"  {k}: {str(v)[:150]}")

print("\n=== 3. SEARCH LOGS FOR TARGET SYMBOLS ===")
symbols = ["MANKIND", "VMM", "VBL", "BSE", "ADANIENT", "GLENMARK", "POLICYBZR", "KFINTECH", "HAL"]
log_files = glob.glob("output/logs/*.log")
for lf in log_files:
    print(f"\nChecking log: {lf}")
    matches = {s: 0 for s in symbols}
    with open(lf, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            for s in symbols:
                if s in line:
                    matches[s] += 1
    for s, cnt in matches.items():
        if cnt > 0:
            print(f"  {s}: {cnt} mentions")
