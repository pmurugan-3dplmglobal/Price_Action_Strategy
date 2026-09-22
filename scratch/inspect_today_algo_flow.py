import subprocess
import sys

SSH_KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

VMS = [
    {
        "name": "VM2 (Bhavani)",
        "ip": "129.225.69.131",
        "user": "opc",
        "dir": "/home/trade/Trade_Kite/Price_Action_Strategy",
        "venv_python": "/home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python"
    },
    {
        "name": "VM1 (Poovendan)",
        "ip": "140.245.197.71",
        "user": "opc",
        "dir": "/home/opc/Price_Action_Strategy",
        "venv_python": "/home/opc/Price_Action_Strategy/venv/bin/python"
    }
]

REMOTE_SCRIPT = r"""#!/usr/bin/env bash
REPO_DIR="__DIR__"
VENV_PYTHON="__VENV_PYTHON__"
cd "$REPO_DIR"

echo "============================================================"
echo "Inspecting DB and Kite Positions on $(hostname)"
echo "============================================================"

$VENV_PYTHON - << 'EOF'
import sys, os, json
sys.path.insert(0, ".")
sys.path.insert(0, "common")
import trade_db
from kiteconnect import KiteConnect

print("--- 1. ACTIVE TRADES IN SQLITE TRADES.DB ---")
active = trade_db.get_active_trades()
print(f"Total active in DB: {len(active)}")
for t in active:
    print(f"  ID={t.get('trade_id')} | sym={t.get('symbol')} | contract={t.get('contract')} | engine={t.get('engine')} | status={t.get('status')} | qty={t.get('quantity')} | entry_time={t.get('entry_time')}")

print("\n--- 2. ALL TRADES RECORDED TODAY (2026-09-10) ---")
all_t = trade_db.get_all_trades()
today_t = [t for t in all_t if str(t.get('entry_time', '')).startswith('2026-09-10') or str(t.get('created_at', '')).startswith('2026-09-10')]
print(f"Total today in DB: {len(today_t)}")
for t in today_t:
    print(f"  ID={t.get('trade_id')} | sym={t.get('symbol')} | contract={t.get('contract')} | engine={t.get('engine')} | pattern={t.get('pattern')} | status={t.get('status')} | qty={t.get('quantity')} | pnl={t.get('pnl')} | entry_time={t.get('entry_time')}")

print("\n--- 3. LIVE KITE NET POSITIONS ---")
try:
    ak_file = "input/api_key.txt"
    at_file = "input/kite_access_token.txt"
    if not os.path.exists(at_file):
        at_file = "Trade_Option/input/kite_access_token.txt"
    if not os.path.exists(ak_file):
        ak_file = "Trade_Option/input/api_key.txt"
    
    with open(ak_file) as f:
        ak = f.read().strip()
    with open(at_file) as f:
        at = f.read().strip()
    
    kite = KiteConnect(api_key=ak)
    kite.set_access_token(at)
    positions = kite.positions()
    net = positions.get("net", [])
    open_pos = [p for p in net if p.get("quantity", 0) != 0]
    print(f"Total open net positions on Kite: {len(open_pos)} (Total net records: {len(net)})")
    for p in open_pos:
        print(f"  sym={p.get('tradingsymbol')} | qty={p.get('quantity')} | product={p.get('product')} | pnl={p.get('pnl')} | value={p.get('value')} | buy_price={p.get('average_price')}")
except Exception as e:
    print(f"Failed to fetch Kite positions: {e}")

print("\n--- 4. PORTFOLIO RISK SETTINGS IN CONFIG ---")
try:
    with open("input/program_config.json") as f:
        cfg = json.load(f)
    print("portfolio_risk:", json.dumps(cfg.get("portfolio_risk", {}), indent=2))
    print("nifty50:", json.dumps(cfg.get("nifty50", {}), indent=2))
    print("index:", json.dumps(cfg.get("index", {}), indent=2))
except Exception as e:
    print(f"Failed to load config: {e}")
EOF

echo ""
echo "--- 5. TODAY JOURNALCTL ENGINE LOGS (BUY / SPREAD / RISK) ---"
journalctl -u trading-options --since "2026-09-10 09:00:00" --until "2026-09-10 12:15:00" --no-pager | grep -iE "DEBIT SPREAD|Spread resolution|PORTFOLIO_RISK|Placed|order_id|BUY|SELL|MAX_CONCURRENT" | tail -n 40 || true
"""

def inspect_vm(vm):
    print(f"\n{'='*60}\nConnecting to {vm['name']} ({vm['ip']})...\n{'='*60}")
    script = (
        REMOTE_SCRIPT
        .replace("__DIR__", vm["dir"])
        .replace("__VENV_PYTHON__", vm["venv_python"])
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    ).encode("utf-8")
    
    cmd = [
        "ssh",
        "-i", SSH_KEY,
        "-o", "StrictHostKeyChecking=no",
        f"{vm['user']}@{vm['ip']}",
        "bash -s"
    ]
    
    p = subprocess.run(cmd, input=script, capture_output=True)
    print(p.stdout.decode("utf-8", errors="replace"))
    if p.stderr:
        print("STDERR:")
        print(p.stderr.decode("utf-8", errors="replace"))

def main():
    for vm in VMS:
        inspect_vm(vm)

if __name__ == "__main__":
    main()
