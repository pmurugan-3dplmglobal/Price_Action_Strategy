import json
import os
import sys
from datetime import datetime as dt, timedelta

COMMON_DIR = os.path.abspath("common")
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

from kiteconnect import KiteConnect
from trading_core import fetch_and_resample_candles, load_kite_session, find_profit_targets

api_k, acc_t = load_kite_session()
kite = KiteConnect(api_key=api_k, access_token=acc_t)

contracts = [
    ('COALINDIA26AUG410CE', 21382914, 8.125, '60minute'),
    ('BEL26AUG390CE', 19383042, 9.2, '75min'),
    ('SHRIRAMFIN26AUG1040CE', 37114626, 26.0, '75min'),
    ('HCLTECH26AUG1340PE', 25305602, 32.525, '75min'),
    ('BAJAJFINSV26AUG1920PE', 4268545, 50.0, '75min')
]

from_d = (dt.now() - timedelta(days=20)).strftime('%Y-%m-%d')
to_d = dt.now().strftime('%Y-%m-%d')

print("=== ANCHOR TIMEFRAME NEGATION SWING TARGETS ===")
for c_name, tok, ep, tf in contracts:
    try:
        df = fetch_and_resample_candles(kite, tok, from_d, to_d, tf)
        t1, t2, t3 = find_profit_targets(df, ep)
        print(f"{c_name} (TF={tf}, Entry={ep}) -> T1={t1}, T2={t2}, T3={t3}")
    except Exception as e:
        print(f"Error for {c_name}: {e}")
