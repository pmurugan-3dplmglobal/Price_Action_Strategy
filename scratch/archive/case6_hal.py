import sys
import os
import datetime as dt
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.session import load_kite_session, ensure_kite_session
from common.paths import TOKEN_FILE
from common.trading_core import fetch_and_resample_candles
from common.resolve import check_spot_anchor_confirmation, evaluate_spot_confluence
from kiteconnect import KiteConnect

ak, at = load_kite_session(TOKEN_FILE)
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)
ensure_kite_session(kite)

# Spot HAL
tok_spot = [i for i in kite.instruments("NSE") if i["tradingsymbol"] == "HAL"][0]["instrument_token"]
from_d = dt.date(2026, 9, 25)
to_d = dt.date(2026, 9, 29)

df_spot_15m = fetch_and_resample_candles(kite, tok_spot, from_d, to_d, "15minute")
print("=== HAL SPOT 15M CANDLES TODAY ===")
today_spot = df_spot_15m[df_spot_15m["date"].astype(str) >= "2026-09-29"]
for idx, r in today_spot.iterrows():
    print(f"{r['date']} | O: {r['open']} | H: {r['high']} | L: {r['low']} | C: {r['close']} | V: {r['volume']}")

# Calculate Spot VWAP at 11:07 AM
sub_1107 = today_spot[today_spot["date"].astype(str) <= "2026-09-29 11:15"]
sp_vol = sub_1107['volume'].values.astype(float)
sp_close = sub_1107['close'].values.astype(float)
sp_high = sub_1107['high'].values.astype(float)
sp_low = sub_1107['low'].values.astype(float)
sp_typ = (sp_high + sp_low + sp_close) / 3.0
vwap_1107 = round(float(sum(sp_typ * sp_vol) / sum(sp_vol)), 2)
cur_spot_1107 = sp_close[-1]

print(f"\nAt 11:07 AM: Spot Close = {cur_spot_1107}, Spot VWAP = {vwap_1107}")
print(f"Is Spot < VWAP? {cur_spot_1107 < vwap_1107}")

# Check check_spot_anchor_confirmation at 11:07
# What was df_spot passed? If only today's df:
has_spot, name = check_spot_anchor_confirmation(sub_1107, "CE", spot_vwap=vwap_1107)
print(f"check_spot_anchor_confirmation(sub_1107, 'CE'): has={has_spot}, name={name}")

has_conf, c_type = evaluate_spot_confluence("CE", False, cur_spot_1107, vwap_1107, cur_spot_1107 * 0.98, True, df_spot=sub_1107)
print(f"evaluate_spot_confluence at 11:07: has={has_conf}, type={c_type}")

# Also test with full multi-day df_spot
has_spot_multi, name_multi = check_spot_anchor_confirmation(df_spot_15m, "CE", spot_vwap=vwap_1107)
print(f"check_spot_anchor_confirmation(df_spot_15m, 'CE'): has={has_spot_multi}, name={name_multi}")
