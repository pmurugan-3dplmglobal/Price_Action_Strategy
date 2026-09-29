import sys
import pandas as pd
from datetime import datetime as dt

sys.path.insert(0, ".")
from common.trading_core import load_kite_session, STOCK_REGISTRY
from kiteconnect import KiteConnect

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

symbols_to_test = [
    # LOSERS / TRAPS
    ("GODREJCP", "CE", "LOSER"),
    ("NMDC", "CE", "LOSER"),
    ("APLAPOLLO", "PE", "LOSER"),
    ("CANBK", "CE", "LOSER"),
    ("ASIANPAINT", "CE", "LOSER"),
    ("RBLBANK", "PE", "LOSER"),
    ("KALYANKJIL", "CE", "LOSER"),
    # WINNERS / MULTIBAGGERS
    ("KEI", "PE", "WINNER"),
    ("PIIND", "PE", "WINNER"),
    ("INFY", "CE", "WINNER"),
    ("TCS", "CE", "WINNER"),
    ("PIDILITIND", "PE", "WINNER"),
    ("SIEMENS", "PE", "WINNER"),
    ("TATAPOWER", "CE", "WINNER")
]

print("=" * 120)
print(f"{'SYMBOL':12} | {'SIDE':4} | {'TYPE':7} | {'SPOT ATR RATIO':14} | {'SPOT RVOL':10} | {'EMA13 vs 44':12} | {'VWAP POS':12} | {'SPOT ANCHOR DETECTED'}")
print("=" * 120)

nse_inst = kite.instruments("NSE")
token_map = {i['tradingsymbol']: i['instrument_token'] for i in nse_inst}

for sym, side, stype in symbols_to_test:
    token = token_map.get(sym)
    if not token:
        continue
        
    try:
        # Fetch 30m candles today
        candles = kite.historical_data(token, "2026-09-20 09:15:00", "2026-09-22 15:30:00", "30minute")
        if not candles or len(candles) < 14:
            continue
        df = pd.DataFrame(candles)
        
        # Calculate Spot ATR(3) / ATR(14)
        tr = (df['high'] - df['low']).abs()
        atr3 = tr.rolling(3).mean().iloc[-1]
        atr14 = tr.rolling(14).mean().iloc[-1]
        spot_atr_ratio = (atr3 / atr14) if atr14 > 0 else 1.0
        
        # Calculate Spot RVOL (Volume / 20-period avg)
        vol_sma20 = df['volume'].rolling(20).mean().iloc[-1] if len(df) >= 20 else df['volume'].mean()
        spot_rvol = (df['volume'].iloc[-1] / vol_sma20) if vol_sma20 > 0 else 1.0
        
        # Calculate EMA13 and EMA44
        df['ema13'] = df['close'].ewm(span=13, adjust=False).mean()
        df['ema44'] = df['close'].ewm(span=44, adjust=False).mean()
        last_c = df['close'].iloc[-1]
        last_e13 = df['ema13'].iloc[-1]
        last_e44 = df['ema44'].iloc[-1]
        
        ema_status = "BULL(13>44)" if last_e13 > last_e44 else "BEAR(13<44)"
        
        # Calculate Intraday VWAP
        # Filter today's candles
        df_today = df[df['date'].astype(str).str.contains("2026-09-22")]
        if not df_today.empty:
            vwap = (df_today['volume'] * (df_today['high'] + df_today['low'] + df_today['close']) / 3).cumsum() / df_today['volume'].cumsum()
            last_vwap = vwap.iloc[-1]
            vwap_pos = "ABOVE_VWAP" if last_c >= last_vwap else "BELOW_VWAP"
        else:
            vwap_pos = "N/A"
            last_vwap = 0.0
            
        # Spot Anchor check
        from common.resolve import check_spot_anchor_confirmation
        has_anchor, anchor_name = check_spot_anchor_confirmation(df, side)
        
        print(f"{sym:12} | {side:4} | {stype:7} | {spot_atr_ratio:<14.2f} | {spot_rvol:<10.2f} | {ema_status:12} | {vwap_pos:12} | {anchor_name} (Confirmed={has_anchor})")
    except Exception as e:
        print(f"Error {sym}: {e}")

print("=" * 120)
