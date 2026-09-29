import subprocess

remote_script = """
import sys
sys.path.insert(0, '/home/opc/Price_Action_Strategy')
sys.path.insert(0, '/home/opc/Price_Action_Strategy/common')
import paths, session, resolve, json
from kiteconnect import KiteConnect
import pandas as pd
from datetime import datetime, timedelta

k, t = session.load_kite_session(paths.TOKEN_FILE)
kite = KiteConnect(api_key=k)
kite.set_access_token(t)

opt_tok = 22133250
spot_tok = 5436929
from_date = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
to_date = datetime.now().strftime('%Y-%m-%d')

candles_opt = kite.historical_data(opt_tok, from_date, to_date, '30minute')
df_opt = pd.DataFrame(candles_opt)
if not df_opt.empty:
    df_opt['color'] = df_opt.apply(lambda r: 'GREEN' if r['close'] >= r['open'] else 'RED', axis=1)
    print("=== AUBANK26SEP1080CE 30m CANDLES (Rows 50 to 95) ===")
    print(df_opt[['date', 'open', 'high', 'low', 'close', 'volume', 'color']].iloc[50:].to_string())


candles_spot = kite.historical_data(spot_tok, from_date, to_date, '30minute')
df_spot = pd.DataFrame(candles_spot)
if not df_spot.empty:
    df_spot['color'] = df_spot.apply(lambda r: 'GREEN' if r['close'] >= r['open'] else 'RED', axis=1)
    print("=== AUBANK SPOT 30m CANDLES (last 20) ===")
    print(df_spot[['date', 'open', 'high', 'low', 'close', 'volume', 'color']].tail(20).to_string())

candles_day = kite.historical_data(spot_tok, (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d'), to_date, 'day')
df_day = pd.DataFrame(candles_day)
if not df_day.empty:
    print("=== AUBANK SPOT DAILY CANDLES (last 10) ===")
    print(df_day[['date', 'open', 'high', 'low', 'close', 'volume']].tail(10).to_string())

from registries import sync_stock_tokens, STOCK_REGISTRY
sync_stock_tokens(kite)
print("After sync, AUBANK config:", STOCK_REGISTRY.get("AUBANK"))

from trading_core import resolve_option_strikes
ce_list = resolve_option_strikes("AUBANK", 1074.0, 20.0, "CE", 2)
pe_list = resolve_option_strikes("AUBANK", 1074.0, 20.0, "PE", 2)
print("Resolved CE strikes for spot 1074:", [c.get("tradingsymbol") for c in ce_list])
print("Resolved PE strikes for spot 1074:", [p.get("tradingsymbol") for p in pe_list])

# Check Scan Display staged trades for AUBANK
scan_disp = json.load(open(paths.SCAN_DISPLAY_FILE))
staged = [x for x in scan_disp.get("staged_trades", []) + scan_disp.get("all_staged_today", []) if "AUBANK" in str(x)]
print(f"Scan Display entries for AUBANK ({len(staged)}):")
print(json.dumps(staged, indent=2))


print(json.dumps(staged, indent=2))


"""

res = subprocess.run([
    'ssh', '-i', r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key',
    '-o', 'StrictHostKeyChecking=no',
    'opc@140.245.197.71',
    '/home/opc/Price_Action_Strategy/venv/bin/python'
], input=remote_script, capture_output=True, text=True)

print(res.stdout)
if res.stderr:
    print("STDERR:", res.stderr)
