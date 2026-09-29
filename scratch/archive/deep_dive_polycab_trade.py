import os, sys, json, sqlite3
from datetime import datetime as dt, timedelta
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import paths
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from session import load_kite_session
from kiteconnect import KiteConnect

monitor = os.path.join(PROJECT_ROOT, "output", "monitor")
print("=== CHECKING LOCAL MONITOR FILES FOR POLYCAB ===")
for fname in ["executed_exit_orders.json", "executed_patterns.json", "journal_trades_db.json", "trades_db.json", "cycle_trades.json"]:
    fpath = os.path.join(monitor, fname)
    if os.path.exists(fpath):
        try:
            with open(fpath, encoding="utf-8") as fh:
                data = json.load(fh)
                text = json.dumps(data)
                if "POLYCAB" in text:
                    print(f"\n[FOUND IN {fname}]")
                    if isinstance(data, dict):
                        for k, v in data.items():
                            if "POLYCAB" in str(k) or "POLYCAB" in str(v):
                                print(f"  Key: {k}")
                                print(f"  Val: {v}")
                    elif isinstance(data, list):
                        for item in data:
                            if "POLYCAB" in str(item):
                                print(f"  Item: {item}")
        except Exception as e:
            print(f"Error reading {fname}: {e}")

sq = os.path.join(monitor, "trades.sqlite3")
if os.path.exists(sq):
    conn = sqlite3.connect(sq)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM trades WHERE symbol LIKE '%POLYCAB%' OR contract LIKE '%POLYCAB%'")
    for r in c.fetchall():
        print("SQLITE trade:", dict(r))

# Connect to Kite to get 1m / 3m candles for spot and option between 09:15 and 10:15 today
api_k, acc_t = load_kite_session(paths.TOKEN_FILE)
kite = KiteConnect(api_key=api_k)
kite.set_access_token(acc_t)

instruments_nse = kite.instruments("NSE")
spot_tok = [i["instrument_token"] for i in instruments_nse if i["tradingsymbol"] == "POLYCAB"][0]

instruments_nfo = kite.instruments("NFO")
opt_tok = [i["instrument_token"] for i in instruments_nfo if i["tradingsymbol"] == "POLYCAB26SEP8300CE"][0]

today_str = dt.now().strftime("%Y-%m-%d")
c_spot = kite.historical_data(spot_tok, f"{today_str} 09:15:00", f"{today_str} 10:30:00", "minute")
c_opt = kite.historical_data(opt_tok, f"{today_str} 09:15:00", f"{today_str} 10:30:00", "minute")

df_spot = pd.DataFrame(c_spot)
df_opt = pd.DataFrame(c_opt)

print("\n=== OPTION CANDLES AROUND ENTRY (09:18 - 09:25) ===")
print(df_opt[(df_opt['date'].dt.hour == 9) & (df_opt['date'].dt.minute >= 18) & (df_opt['date'].dt.minute <= 25)][['date', 'open', 'high', 'low', 'close', 'volume']].to_string(index=False))

print("\n=== SPOT CANDLES AROUND ENTRY (09:18 - 09:25) ===")
print(df_spot[(df_spot['date'].dt.hour == 9) & (df_spot['date'].dt.minute >= 18) & (df_spot['date'].dt.minute <= 25)][['date', 'open', 'high', 'low', 'close', 'volume']].to_string(index=False))

print("\n=== OPTION CANDLES AROUND EXIT (09:45 - 09:55) ===")
print(df_opt[(df_opt['date'].dt.hour == 9) & (df_opt['date'].dt.minute >= 45) & (df_opt['date'].dt.minute <= 55)][['date', 'open', 'high', 'low', 'close', 'volume']].to_string(index=False))

print("\n=== SPOT CANDLES AROUND EXIT (09:45 - 09:55) ===")
print(df_spot[(df_spot['date'].dt.hour == 9) & (df_spot['date'].dt.minute >= 45) & (df_spot['date'].dt.minute <= 55)][['date', 'open', 'high', 'low', 'close', 'volume']].to_string(index=False))

print("\n=== OPTION HIGH/LOW FOR THE DAY SO FAR ===")
print(f"Option High: {df_opt['high'].max()} at {df_opt.loc[df_opt['high'].idxmax()]['date']}")
print(f"Option Low : {df_opt['low'].min()} at {df_opt.loc[df_opt['low'].idxmin()]['date']}")
print(f"Option Latest: {df_opt.iloc[-1]['close']} at {df_opt.iloc[-1]['date']}")
