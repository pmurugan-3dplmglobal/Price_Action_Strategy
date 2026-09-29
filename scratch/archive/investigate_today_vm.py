"""
Forensic Investigation: Why No Trade Triggered on Poovendan VM 1 Today (2026-09-28)
"""
import subprocess
import json
import sys

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
VM_IP = "140.245.197.71"
VM_USER = "opc"
REMOTE_REPO = "/home/opc/Price_Action_Strategy"

def run_ssh(cmd):
    res = subprocess.run([
        "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
        f"{VM_USER}@{VM_IP}", cmd
    ], capture_output=True, text=True, timeout=30)
    return res.stdout, res.stderr

print("=" * 80)
print("1. CHECKING RUNNING PROCESSES (Engines, Scanners, Dashboards)")
print("=" * 80)
out, err = run_ssh("ps aux | grep python3 | grep -v grep; ps aux | grep python | grep -v grep")
print(out or "NO PYTHON PROCESSES FOUND!")

print("\n" + "=" * 80)
print("2. CHECKING LIVE FLAGS (input/nifty50_live.flag, input/index_live.flag)")
print("=" * 80)
out, err = run_ssh(f"ls -la {REMOTE_REPO}/input/*.flag {REMOTE_REPO}/Trade_Option/input/*.flag 2>/dev/null")
print(out or "NO LIVE FLAGS FOUND (System may be in Paper/Scan-Only mode!)")

print("\n" + "=" * 80)
print("3. CHECKING TODAY'S TRADE JOURNAL (output/monitor/trade_journal.csv)")
print("=" * 80)
out, err = run_ssh(f"grep '2026-09-28' {REMOTE_REPO}/output/monitor/trade_journal.csv | tail -n 25")
print(out or "NO JOURNAL ENTRIES FOR TODAY (2026-09-28)!")

print("\n" + "=" * 80)
print("4. CHECKING TODAY'S JOURNAL EVENT BREAKDOWN")
print("=" * 80)
out, err = run_ssh(f"grep '2026-09-28' {REMOTE_REPO}/output/monitor/trade_journal.csv | awk -F'\t' '{{print $5, $6}}' | sort | uniq -c")
print(out or "NO JOURNAL STATS FOR TODAY")

print("\n" + "=" * 80)
print("5. CHECKING LATEST LOGS: bull_nifty50_scanner.log (Stock Options Engine)")
print("=" * 80)
out, err = run_ssh(f"tail -n 35 {REMOTE_REPO}/output/logs/bull_nifty50_scanner.log 2>/dev/null")
print(out or "bull_nifty50_scanner.log is empty or missing")

print("\n" + "=" * 80)
print("6. CHECKING LATEST LOGS: bull_index_trade_engine.log (Index Options Engine)")
print("=" * 80)
out, err = run_ssh(f"tail -n 35 {REMOTE_REPO}/output/logs/bull_index_trade_engine.log 2>/dev/null")
print(out or "bull_index_trade_engine.log is empty or missing")

print("\n" + "=" * 80)
print("7. CHECKING SCAN DISPLAY (output/monitor/scan_display.json - Staged Candidates)")
print("=" * 80)
script = f"""
import json, os
p = '{REMOTE_REPO}/output/monitor/scan_display.json'
if os.path.exists(p):
    d = json.load(open(p))
    staged = d.get('staged_trades', [])
    print(f"Staged trades count: {{len(staged)}}")
    for s in staged[:10]:
        print(f"  {{s.get('symbol')}} {{s.get('contract')}} | Pat: {{s.get('pattern')}} | Tier: {{s.get('tier_badge')}} | BM: {{s.get('benchmark')}} | SpotConf: {{s.get('spot_confluence')}}")
else:
    print("scan_display.json not found")
"""
out, err = run_ssh(f"{REMOTE_REPO}/venv/bin/python -c \"{script}\"")
print(out or err)

print("\n" + "=" * 80)
print("8. CHECKING PATTERN FUNNEL (output/monitor/pattern_funnel.json - A+, A, B)")
print("=" * 80)
script_funnel = f"""
import json, os
p = '{REMOTE_REPO}/output/monitor/pattern_funnel.json'
if os.path.exists(p):
    d = json.load(open(p))
    for eng, data in d.items():
        if isinstance(data, dict):
            ap = len(data.get('category_a_plus', []))
            a = len(data.get('category_a', []))
            b = len(data.get('category_b', []))
            print(f"Engine: {{eng}} -> A+: {{ap}}, A: {{a}}, B: {{b}}")
"""
out, err = run_ssh(f"{REMOTE_REPO}/venv/bin/python -c \"{script_funnel}\"")
print(out or err)

print("\n" + "=" * 80)
print("9. CHECKING ACTIVE POSITIONS & TRADES DB TODAY")
print("=" * 80)
script_db = f"""
import sqlite3, os
p = '{REMOTE_REPO}/output/monitor/trades.sqlite3'
if os.path.exists(p):
    conn = sqlite3.connect(p)
    c = conn.cursor()
    c.execute("SELECT id, symbol, contract, status, created_at FROM trades WHERE created_at LIKE '2026-09-28%' ORDER BY id DESC")
    rows = c.fetchall()
    print(f"Trades created today: {{len(rows)}}")
    for r in rows:
        print(f"  ID {{r[0]}}: {{r[1]}} {{r[2]}} -> Status: {{r[3]}} ({{r[4]}})")
    conn.close()
"""
out, err = run_ssh(f"{REMOTE_REPO}/venv/bin/python -c \"{script_db}\"")
print(out or err)
