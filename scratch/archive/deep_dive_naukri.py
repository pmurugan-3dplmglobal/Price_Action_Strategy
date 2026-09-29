import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
py_code = """
import sys, os, json, sqlite3
from datetime import datetime as dt, timedelta
sys.path.insert(0, os.path.abspath("common"))
from trading_core import load_kite_session
from kiteconnect import KiteConnect

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

# 1. Query trades.sqlite3 for all NAUKRI records
conn = sqlite3.connect("output/monitor/trades.sqlite3")
c = conn.cursor()
c.execute("SELECT id, symbol, contract, status, created_at, updated_at, data_json FROM trades WHERE symbol LIKE '%NAUKRI%' OR contract LIKE '%NAUKRI%' ORDER BY id DESC")
rows = c.fetchall()
print("=== NAUKRI TRADES IN DATABASE ===")
for r in rows:
    tid, sym, cnt, st, cat, uat, dj = r
    d = json.loads(dj) if dj else {}
    print(f"ID: {tid} | {sym} ({cnt}) | Status: {st} | Created: {cat} | Updated: {uat}")
    print(f"  Entry: {d.get('entry_spot') or d.get('entry_price')} | Exit: {d.get('exit_price')} | Reason: {d.get('exit_reason')}")
    print(f"  SL: {d.get('current_sl')} | T1: {d.get('t1')} | Pattern: {d.get('pattern')} | TF: {d.get('timeframe') or d.get('timeframe_anchor')}")
    print(f"  Underlying SL: {d.get('underlying_sl')} | Anchor Low: {d.get('anchor_low')} | Benchmark: {d.get('benchmark')}")

# 2. Get Instrument Tokens for NAUKRI spot and options
instruments = kite.instruments("NFO")
naukri_token = None
for inst in instruments:
    if inst.get("tradingsymbol") == "NAUKRI26SEP1300PE":
        naukri_token = inst.get("instrument_token")
        break

# NSE spot instrument
nse_insts = kite.instruments("NSE")
spot_token = None
for inst in nse_insts:
    if inst.get("tradingsymbol") in ["NAUKRI", "INFOEDGE"]:
        spot_token = inst.get("instrument_token")
        spot_symbol = inst.get("tradingsymbol")
        break

print(f"Tokens -> NAUKRI Spot ({spot_symbol}): {spot_token} | NAUKRI 1300 PE: {naukri_token}")

from timeframe_utils import get_ist_now
now_ist = get_ist_now(naive=True)
today_str = now_ist.strftime("%Y-%m-%d")
from_dt = f"{today_str} 09:15:00"
to_dt = now_ist.strftime("%Y-%m-%d %H:%M:%S")

# 3. Fetch 5-minute candles for NAUKRI Spot
if spot_token:
    try:
        spot_candles = kite.historical_data(spot_token, from_dt, to_dt, "5minute")
        print(f"=== NAUKRI SPOT 5-MIN CANDLES TODAY ({len(spot_candles)}) ===")
        for c in spot_candles[-15:]:
            t = c.get("date")
            o, h, l, cl, v = c.get("open"), c.get("high"), c.get("low"), c.get("close"), c.get("volume")
            print(f"[{t}] O:{o} H:{h} L:{l} C:{cl} Vol:{v}")
    except Exception as se:
        print(f"Spot candle error: {se}")

if naukri_token:
    try:
        opt_candles = kite.historical_data(naukri_token, from_dt, to_dt, "5minute")
        print(f"=== NAUKRI 1300 PE 5-MIN CANDLES TODAY ({len(opt_candles)}) ===")
        for c in opt_candles[-15:]:
            t = c.get("date")
            o, h, l, cl, v = c.get("open"), c.get("high"), c.get("low"), c.get("close"), c.get("volume")
            print(f"[{t}] O:{o} H:{h} L:{l} C:{cl} Vol:{v}")
    except Exception as oe:
        print(f"Opt candle error: {oe}")

# 4. Fetch 5-minute candles for NAUKRI 1300 PE
if naukri_token:
    opt_candles = kite.historical_data(naukri_token, from_dt, to_dt, "5minute")
    print(f"=== NAUKRI 1300 PE 5-MIN CANDLES TODAY ({len(opt_candles)}) ===")
    for c in opt_candles:
        t = c.get("date")
        o, h, l, cl, v = c.get("open"), c.get("high"), c.get("low"), c.get("close"), c.get("volume")
        print(f"[{t}] O:{o} H:{h} L:{l} C:{cl} Vol:{v}")
"""

cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@140.245.197.71", "cd /home/opc/Price_Action_Strategy && ./venv/bin/python -"]
res = subprocess.run(cmd, input=py_code, capture_output=True, text=True, encoding="utf-8", errors="replace")
print(res.stdout or res.stderr)
