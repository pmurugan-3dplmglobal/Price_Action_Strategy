import subprocess

SSH_KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

BASH_SCRIPT = r"""#!/usr/bin/env bash
cd /home/trade/Trade_Kite/Price_Action_Strategy

/home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python - << 'PYEOF'
import sys, os, json
sys.path.insert(0, '.')
sys.path.insert(0, 'common')
import trade_db
from kiteconnect import KiteConnect

print("=== 1. TCS TRADE IN TRADE_DB ===")
active_trades = trade_db.get_active_trades()
for t in active_trades:
    if 'TCS' in str(t.get('symbol')) or 'TCS' in str(t.get('contract')):
        print(json.dumps(t, indent=2))

print("\n=== 2. PROGRAM CONFIG PAUSE FLAGS ===")
with open('input/program_config.json') as f:
    cfg = json.load(f)
print("pause_sl_monitor:", cfg.get("pause_sl_monitor"))
print("failsafe_start_time:", cfg.get("failsafe_start_time"))
print("nifty50 config:", json.dumps(cfg.get("nifty50", {}), indent=2))

print("\n=== 3. KITE POSITION & QUOTE FOR TCS ===")
ak = "jgdjmtymfyea4yn4"
at_data = json.loads(open("input/kite_access_token.txt").read().strip())
at = at_data.get("access_token")
kite = KiteConnect(api_key=ak, access_token=at)
positions = kite.positions().get("net", [])
for p in positions:
    if 'TCS' in p.get("tradingsymbol", ""):
        print("Kite Net Pos:", p.get("tradingsymbol"), "Qty:", p.get("quantity"), "AvgPrice:", p.get("average_price"), "PnL:", p.get("pnl"), "M2M:", p.get("m2m"))

quotes = kite.quote(["NFO:TCS26SEP2200CE", "NSE:TCS"])
print("TCS Spot Quote:", quotes.get("NSE:TCS", {}).get("last_price"))
print("TCS Option Quote:", quotes.get("NFO:TCS26SEP2200CE", {}).get("last_price"))
print("TCS Option OHLC:", quotes.get("NFO:TCS26SEP2200CE", {}).get("ohlc"))

print("\n=== 4. ACTIVE_POSITIONS_DB / MONITOR STATE ===")
for fname in ["output/monitor/active_positions_db.json", "output/monitor/stock_positions_state.json", "output/monitor/trades_db.json"]:
    if os.path.exists(fname):
        print(f"--- {fname} ---")
        try:
            with open(fname) as f:
                c = json.load(f)
                if isinstance(c, dict):
                    for k, v in c.items():
                        if 'TCS' in str(k) or 'TCS' in str(v):
                            print(k, "->", json.dumps(v, indent=2))
                elif isinstance(c, list):
                    for item in c:
                        if 'TCS' in str(item):
                            print(json.dumps(item, indent=2))
        except Exception as e:
            print(f"Error reading {fname}: {e}")

PYEOF

echo ""
echo "=== 5. ENGINE LOGS FOR TCS ===")
grep -i "TCS" output/logs/bull_nifty50_scanner.log 2>/dev/null | tail -n 30 || true

echo ""
echo "=== 6. JOURNALCTL FOR TCS ==="
journalctl -u trading-options --since "2026-09-10 10:30:00" --no-pager | grep -i "TCS" | tail -n 30 || true
"""

def main():
    p = subprocess.run(
        ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", "opc@129.225.69.131", "bash -s"],
        input=BASH_SCRIPT.replace("\r\n", "\n").encode("utf-8"),
        capture_output=True
    )
    print(p.stdout.decode("utf-8", errors="replace"))
    if p.stderr:
        print("STDERR:", p.stderr.decode("utf-8", errors="replace"))

if __name__ == "__main__":
    main()
