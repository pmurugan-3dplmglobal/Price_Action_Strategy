import subprocess
import json

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

for name, ip, rdir in [('Poovendan VM', '140.245.197.71', '/home/opc/Price_Action_Strategy'), ('Bhavni VM', '129.225.69.131', '/home/trade/Trade_Kite/Price_Action_Strategy')]:
    print("=" * 80)
    print(f"FETCHING TODAY'S ACTUAL TRADES FROM {name} ({ip})")
    print("=" * 80)
    cmd = [
        "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"opc@{ip}",
        f"python3 -c \"import sqlite3, json; conn = sqlite3.connect('{rdir}/output/monitor/trades.sqlite3'); c = conn.cursor(); c.execute('SELECT id, symbol, contract, status, created_at, data_json FROM trades ORDER BY id DESC LIMIT 20'); rows = c.fetchall(); [print(r[0], r[1], r[2], r[3], r[4], json.loads(r[5]).get('entry_price'), json.loads(r[5]).get('exit_price'), json.loads(r[5]).get('pnl_percent'), json.loads(r[5]).get('pnl_amount'), json.loads(r[5]).get('exit_reason') or json.loads(r[5]).get('details')) for r in rows if str(r[4]).startswith('2026-09-21')]\""
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    print(res.stdout.strip() or res.stderr.strip() or "No trades found for today.")
