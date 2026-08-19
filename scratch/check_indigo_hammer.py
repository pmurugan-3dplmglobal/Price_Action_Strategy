import sys, os
sys.path.insert(0, os.path.abspath('common'))
from session import load_kite_session
from trading_core import fetch_and_resample_candles, scan_anchor_bcd_breakout
from kiteconnect import KiteConnect

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

insts = kite.instruments('NFO')
target = [i for i in insts if i['tradingsymbol'] == 'INDIGO26AUG5200CE']
if not target:
    print('Instrument not found!')
    sys.exit(1)

tok = target[0]['instrument_token']
from datetime import datetime as dt, timedelta

to_date = dt.now()
from_date = to_date - timedelta(days=5)

for tf in ['15minute', '30minute']:
    df = fetch_and_resample_candles(kite, tok, from_date, to_date, tf)
    print(f"\n=== TIMEFRAME: {tf} ===")
    today_df = df[df['date'].astype(str).str.contains('2026-08-18')]
    for idx, row in today_df.iterrows():
        o, h, l, c = row['open'], row['high'], row['low'], row['close']
        body = round(abs(c - o), 2)
        lower_wick = round(min(o, c) - l, 2)
        upper_wick = round(h - max(o, c), 2)
        is_green = c >= o
        print(f"{row['date']} | O: {o:6.2f} | H: {h:6.2f} | L: {l:6.2f} | C: {c:6.2f} | Body: {body:5.2f} | LowerWick: {lower_wick:5.2f} | UpperWick: {upper_wick:5.2f} | {'GREEN' if is_green else 'RED'}")

df_entry = fetch_and_resample_candles(kite, tok, from_date, to_date, '30minute')
df_anchor = fetch_and_resample_candles(kite, tok, from_date, to_date, '30minute')
res = scan_anchor_bcd_breakout(df_entry, df_anchor, anchor_tf='30minute', entry_tf='30minute')
print("\n=== SCAN RESULT ===")
print(res)

