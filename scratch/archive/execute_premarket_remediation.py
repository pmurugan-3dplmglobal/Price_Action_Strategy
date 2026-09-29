import subprocess

SSH_KEY = r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key'
VM1_IP = '140.245.197.71'
VM2_IP = '129.225.69.131'

vm1_bash = """#!/usr/bin/env bash
set -e
echo '=== Killing rogue engine processes 116452 116453 ==='
sudo kill -9 116452 116453 2>/dev/null || echo 'Processes already terminated'

echo '=== Updating ghost trade 830 in SQLite DB ==='
python3 -c "
import sqlite3, os
db_path = '/home/opc/Price_Action_Strategy/output/monitor/trades.sqlite3'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('SELECT id, symbol, contract, status FROM trades WHERE id=830')
    row = cur.fetchone()
    if row:
        print('Found trade 830:', row)
        cur.execute(\\"UPDATE trades SET status='REJECTED_MARGIN', updated_at=datetime('now') WHERE id=830\\")
        conn.commit()
        print('Successfully marked trade 830 as REJECTED_MARGIN')
    else:
        print('Trade 830 not found')
    conn.close()
"

echo '=== Pulling latest git commit on VM1 ==='
cd /home/opc/Price_Action_Strategy
git pull origin master

echo '=== VM1 Memory and Load ==='
uptime
free -h
"""

print('--- Executing cleanup on VM1 ---')
cmd1 = ['ssh', '-i', SSH_KEY, '-o', 'StrictHostKeyChecking=no', f'opc@{VM1_IP}', 'bash -s']
res1 = subprocess.run(cmd1, input=vm1_bash.encode('utf-8'), capture_output=True)
print(res1.stdout.decode('utf-8', errors='replace'))
if res1.stderr:
    print('STDERR:', res1.stderr.decode('utf-8', errors='replace'))

vm2_bash = """#!/usr/bin/env bash
set -e
echo '=== Pulling latest git commit on VM2 ==='
cd /home/trade/Trade_Kite/Price_Action_Strategy
git pull origin master
uptime
free -h
"""

print('--- Executing git pull on VM2 ---')
cmd2 = ['ssh', '-i', SSH_KEY, '-o', 'StrictHostKeyChecking=no', f'opc@{VM2_IP}', 'bash -s']
res2 = subprocess.run(cmd2, input=vm2_bash.encode('utf-8'), capture_output=True)
print(res2.stdout.decode('utf-8', errors='replace'))
if res2.stderr:
    print('STDERR:', res2.stderr.decode('utf-8', errors='replace'))
