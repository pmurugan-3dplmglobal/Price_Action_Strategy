import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="ignore")

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
HOST = "opc@140.245.197.71"
REMOTE_DIR = "/home/opc/Price_Action_Strategy"

cmd = f"""python3 -c "
import json, os, glob

print('=== 140.245.197.71 TOKEN FILES ===')
for p in glob.glob('{REMOTE_DIR}/**/kite_access_token.txt', recursive=True):
    try:
        with open(p) as f:
            d = json.load(f)
        print(f'Path: {{p}} | Generated: {{d.get(\"generated_at\")}} | API Key: {{d.get(\"api_key\")}}')
    except Exception as e:
        print(f'Path: {{p}} | Err: {{e}}')

print('\n=== CONFIG FILE ===')
try:
    with open('{REMOTE_DIR}/input/program_config.json') as f:
        cfg = json.load(f)
    print('API Key:', cfg.get('api_key'))
except Exception as e:
    print('Config Err:', e)

print('\n=== ACTIVE TRADES IN SQLITE ===')
try:
    import sqlite3
    db = '{REMOTE_DIR}/output/monitor/trades.sqlite3'
    if os.path.exists(db):
        conn = sqlite3.connect(db)
        cur = conn.cursor()
        cur.execute('SELECT id, engine, symbol, contract, status, created_at FROM trades WHERE status = \"ACTIVE\"')
        rows = cur.fetchall()
        print(f'Active rows: {{len(rows)}}')
        for r in rows:
            print(' ', r)
        conn.close()
    else:
        print('No trades.sqlite3 found')
except Exception as e:
    print('DB Err:', e)
" """

res = subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd], capture_output=True, text=True)
print(res.stdout)
