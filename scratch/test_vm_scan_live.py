import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
VM_IP = "140.245.197.71"
VM_USER = "opc"
PYTHON_BIN = "/home/opc/Price_Action_Strategy/venv/bin/python"

script = """
import sys
sys.path.insert(0, '/home/opc/Price_Action_Strategy')
from common.session import load_kite_session
from kiteconnect import KiteConnect
import logging

logging.basicConfig(level=logging.INFO)

k, tok = load_kite_session()
kite = KiteConnect(api_key=k)
kite.set_access_token(tok)

print("Kite authenticated successfully. Testing 1 stock scan via scan_symbol...")
from common.trading_core import scan_symbol, scan_anchor_bcd_breakout, scan_trend_continuation_reentry, find_anchor_bullish_engulfing, find_anchor_ll_sweep, find_anchor_hammer_baby, find_anchor_bullish_harami, find_anchor_two_higher_highs, resolve_option_strikes as shared_resolve_strikes, match_registry_symbol, get_option_lot_size
import trade_db, threading

entry_scanners = [("Setup_1_Anchor_BCD", scan_anchor_bcd_breakout), ("Setup_2_Trend_Continuation", scan_trend_continuation_reentry)]
anchor_scanners = [("A1", find_anchor_bullish_engulfing), ("A2", find_anchor_ll_sweep), ("A3", find_anchor_hammer_baby), ("A4", find_anchor_bullish_harami), ("A5", find_anchor_two_higher_highs)]
pos_lock = threading.Lock()

from common.registries import STOCK_REGISTRY
cfg = STOCK_REGISTRY.get("RELIANCE", {})
print("Scanning RELIANCE...")
try:
    res = scan_symbol(
        kite, "RELIANCE", cfg,
        "2026-09-20", "2026-09-28", "2026-09-10", "2026-09-28",
        entry_scanners, anchor_scanners,
        lambda sym, sp, step, opt, r: [],
        "nifty50", "15minute", "30minute", "15minute",
        {}, pos_lock, trade_db, 1,
        lambda *args: None
    )
    print("Scan SUCCESS! Candidates found:", len(res))
except Exception as e:
    import traceback
    print("Scan CRASHED with exception:")
    traceback.print_exc()
"""

res = subprocess.run([
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
    f"{VM_USER}@{VM_IP}",
    PYTHON_BIN
], input=script, capture_output=True, text=True, timeout=60)

print(res.stdout)
if res.stderr:
    print("STDERR:\n", res.stderr)
