import sys
import os
import datetime as dt
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.session import load_kite_session, ensure_kite_session
from common.paths import TOKEN_FILE
from common.trading_core import fetch_and_resample_candles
from common.patterns_bull import scan_pattern_lifecycle_stage
from kiteconnect import KiteConnect

ak, at = load_kite_session(TOKEN_FILE)
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)
ensure_kite_session(kite)

# Check VBL options: VBL26OCT430CE, VBL26OCT430PE
# BSE options: BSE26OCT3100CE, BSE26OCT3200CE, PE?
# VMM options: VMM26OCT105CE, VMM26OCT105PE
nfo_instruments = kite.instruments("NFO")

contracts = ["VBL26OCT430CE", "VBL26OCT430PE", "VMM26OCT105CE", "VMM26OCT105PE", "BSE26OCT3200CE", "BSE26OCT3000PE", "BSE26OCT3100PE"]

from_d = dt.date(2026, 9, 25)
to_d = dt.date(2026, 9, 29)

for cnt in contracts:
    match = [i for i in nfo_instruments if i["tradingsymbol"] == cnt]
    if not match:
        print(f"Contract {cnt} not found")
        continue
    tok = match[0]["instrument_token"]
    df_15m = fetch_and_resample_candles(kite, tok, from_d, to_d, "15minute")
    df_75m = fetch_and_resample_candles(kite, tok, from_d, to_d, "75minute")
    
    stage = scan_pattern_lifecycle_stage(df_15m, df_75m, anchor_tf="75minute", entry_tf="15minute", is_option=True)
    print(f"\nContract: {cnt}")
    print(f"  Stage: {stage.get('stage') if stage else 'None'}")
    if stage:
        print(f"  Pattern: {stage.get('pattern')}, Close: {stage.get('close')}, BM: {stage.get('benchmark')}, SL: {stage.get('sl')}, RR: {stage.get('rr')}")
        print(f"  A_time: {stage.get('candle_a_time')}, B_time: {stage.get('candle_b_time')}, C_time: {stage.get('candle_c_time')}")
