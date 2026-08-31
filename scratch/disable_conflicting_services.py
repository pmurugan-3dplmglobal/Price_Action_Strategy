import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="ignore")

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
HOST = "opc@140.245.197.71"

cmd = """
sudo systemctl stop tradingview-options tradingview-stock tradingview-export trading-fyers-options trading-fyers-stock trading-fyers-export || true
sudo systemctl disable tradingview-options tradingview-stock tradingview-export trading-fyers-options trading-fyers-stock trading-fyers-export || true
sudo pkill -9 -f Price_Action_TradingView || true
sudo systemctl restart trading-options trading-stock trading-export
"""

res = subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd], capture_output=True, text=True)
print("=== DISABLED CONFLICTING SERVICES ON 140.245.197.71 ===")
print(res.stdout)
print(res.stderr)
