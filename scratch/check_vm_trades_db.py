import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

for name, ip, rdir in [('Poovendan', '140.245.197.71', '/home/opc/Price_Action_Strategy'), ('Bhavni', '129.225.69.131', '/home/trade/Trade_Kite/Price_Action_Strategy')]:
    cmd = [
        "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"opc@{ip}",
        f"python3 -c \"import sqlite3; conn = sqlite3.connect('{rdir}/output/monitor/trades.sqlite3'); c = conn.cursor(); c.execute('SELECT id, symbol, contract, status, created_at FROM trades ORDER BY id DESC LIMIT 10'); rows = c.fetchall(); print('{name} DB:'); [print(r) for r in rows]\""
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    print(res.stdout.strip() or res.stderr.strip())
