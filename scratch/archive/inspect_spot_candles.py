import os
import sys
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from kiteconnect import KiteConnect
from common.session import load_kite_session, ensure_kite_session
from common.paths import TOKEN_FILE

api_key, access_token = load_kite_session(TOKEN_FILE)
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)
ensure_kite_session(kite)

nse_instruments = kite.instruments("NSE")
nse_map = {inst["tradingsymbol"]: inst["instrument_token"] for inst in nse_instruments}

to_dt = datetime.now()
from_dt = to_dt - timedelta(days=12)

print("=" * 60)
print("COLPAL SPOT 30-MINUTE CANDLES")
print("=" * 60)
colpal_token = nse_map.get("COLPAL")
candles = kite.historical_data(colpal_token, from_dt, to_dt, "30minute")
df_colpal = pd.DataFrame(candles)
print(df_colpal.tail(15)[['date', 'open', 'high', 'low', 'close', 'volume']])

print("\n" + "=" * 60)
print("MOTHERSON SPOT 30-MINUTE CANDLES (Yesterday & Today)")
print("=" * 60)
motherson_token = nse_map.get("MOTHERSON")
m_candles = kite.historical_data(motherson_token, from_dt, to_dt, "30minute")
df_motherson = pd.DataFrame(m_candles)
print(df_motherson.tail(15)[['date', 'open', 'high', 'low', 'close', 'volume']])
