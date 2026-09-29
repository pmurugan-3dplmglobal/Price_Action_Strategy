import subprocess
import os

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
VMS = [
    ("VM1 (Poovendan)", "opc@140.245.197.71", "/home/opc/Price_Action_Strategy"),
    ("VM2 (Bhavani)", "opc@129.225.69.131", "/home/trade/Trade_Kite/Price_Action_Strategy")
]

snippet = """
import sqlite3, json, os

db = 'output/monitor/trades.sqlite3'
if os.path.exists(db):
    conn = sqlite3.connect(db)
    c = conn.cursor()
    c.execute("SELECT id, engine, symbol, contract, status, created_at, updated_at, data_json FROM trades WHERE created_at LIKE '2026-09-23%' OR updated_at LIKE '2026-09-23%' ORDER BY id DESC")
    rows = c.fetchall()
    print(f"Total Trades Today: {len(rows)}")
    for r in rows:
        tid, eng, sym, cnt, st, cat, uat, dj = r
        d = json.loads(dj) if dj else {}
        ep = d.get('entry_price') or d.get('entry_spot') or d.get('buy_price')
        xp = d.get('exit_price')
        pnl = d.get('pnl') or d.get('realized_pnl')
        pct = d.get('pnl_pct') or d.get('pnl_percentage')
        reas = d.get('exit_reason') or d.get('reason')
        t1 = d.get('t1')
        t2 = d.get('t2')
        sl = d.get('current_sl') or d.get('sl')
        ptype = d.get('position_type')
        leg2 = d.get('leg2_contract')
        tier = d.get('tier') or d.get('priority_tier')
        pattern = d.get('pattern')
        tf = d.get('timeframe') or d.get('timeframe_anchor')
        print(f"ID: {tid} | {sym} ({cnt}) | Pat: {pattern} | TF: {tf} | Tier: {tier} | Type: {ptype} | Entry: {ep} | Exit: {xp} | SL: {sl} | T1: {t1} | T2: {t2} | PnL: {pnl} ({pct}%) | Status: {st} | Reason: {reas} | Created: {cat}")
"""

for name, host, cdir in VMS:
    print(f"\n============================== {name} ==============================")
    cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", host, f"cd {cdir} && python3 -"]
    res = subprocess.run(cmd, input=snippet, capture_output=True, text=True)
    print(res.stdout or res.stderr)
