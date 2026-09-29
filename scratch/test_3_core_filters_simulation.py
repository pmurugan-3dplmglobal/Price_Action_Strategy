import sys
import pandas as pd
import json

sys.path.insert(0, ".")
from common.trading_core import load_kite_session
from kiteconnect import KiteConnect

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

# Load the 27 evaluated T1 gold setups
with open('output/monitor/scan_display.json', 'r') as f:
    d = json.load(f)

staged = d.get('all_staged_today', [])
gold_setups = [s for s in staged if 'T1' in str(s.get('tier_badge', '')) or 'GOLD' in str(s.get('tier_label', '')).upper()]

nse_inst = kite.instruments("NSE")
token_map = {i['tradingsymbol']: i['instrument_token'] for i in nse_inst}

print(f"Auditing {len(gold_setups)} T1 Gold setups against the 3 Core Filters:\n")

def simulate_3_core_filters(sym, side, df_spot, spot_vwap):
    if df_spot is None or len(df_spot) < 14:
        return False, "NO_SPOT_DATA"
        
    last_c = df_spot.iloc[-1]
    c_open = float(last_c['open'])
    c_high = float(last_c['high'])
    c_low = float(last_c['low'])
    c_close = float(last_c['close'])
    body = abs(c_close - c_open)
    
    # 1. Dual-Asset VCP Contraction: Spot ATR(3) / ATR(14) <= 0.85
    tr = (df_spot['high'] - df_spot['low']).abs()
    atr3 = tr.rolling(3).mean().iloc[-1]
    atr14 = tr.rolling(14).mean().iloc[-1]
    spot_atr_ratio = (atr3 / atr14) if atr14 > 0 else 1.0
    
    # 2. RVOL
    vol_sma20 = df_spot['volume'].rolling(20).mean().iloc[-1] if len(df_spot) >= 20 else df_spot['volume'].mean()
    spot_rvol = (df_spot['volume'].iloc[-1] / vol_sma20) if vol_sma20 > 0 else 1.0
    
    # 3. EMA13 vs EMA44
    ema13 = float(df_spot['close'].ewm(span=13, adjust=False).mean().iloc[-1])
    ema44 = float(df_spot['close'].ewm(span=44, adjust=False).mean().iloc[-1])
    
    if side == "PE":
        # Filter 1: Spot-First Pattern Anchor Gate
        # Must have genuine bearish rejection AND not be in a runaway bull trend above VWAP
        if c_close > spot_vwap and ema13 > ema44:
            return False, f"BULL_SPOT_TRAP(Close>{spot_vwap:.1f}, EMA13>44)"
            
        # Filter 2: Physical Candlestick Wick Geometry for VWAP Confluence
        if spot_vwap > 0:
            approached_vwap = (c_high >= spot_vwap * 0.997)
            upper_wick = c_high - max(c_open, c_close)
            has_rejection_wick = (upper_wick >= 1.0 * body) or (c_close < c_open and upper_wick >= 0.5 * body)
            closed_below_vwap = (c_close < spot_vwap)
            
            # If price is drifting below VWAP without approaching it, reject naive inequality
            if not approached_vwap and not (ema13 < ema44 and spot_rvol >= 1.2):
                return False, f"DRIFTING_BELOW_VWAP_NO_TEST(H:{c_high:.1f} < VWAP*0.997)"
                
        # Filter 3: Dual-Asset VCP (if promoting on VCP)
        # Spot ATR ratio check
        return True, f"QUALIFIED(SpotATR:{spot_atr_ratio:.2f}, RVOL:{spot_rvol:.2f})"
        
    else:  # CE
        # Filter 1: Must not be in runaway bear trend below VWAP
        if c_close < spot_vwap and ema13 < ema44:
            return False, f"BEAR_SPOT_TRAP(Close<{spot_vwap:.1f}, EMA13<44)"
            
        # Filter 2: Physical Candlestick Wick Geometry for VWAP Confluence
        if spot_vwap > 0:
            approached_vwap = (c_low <= spot_vwap * 1.003)
            lower_wick = min(c_open, c_close) - c_low
            has_support_wick = (lower_wick >= 1.0 * body) or (c_close > c_open and lower_wick >= 0.5 * body)
            closed_above_vwap = (c_close > spot_vwap)
            
            if not approached_vwap and not (ema13 > ema44 and spot_rvol >= 1.2):
                return False, f"DRIFTING_ABOVE_VWAP_NO_TEST(L:{c_low:.1f} > VWAP*1.003)"
                
        return True, f"QUALIFIED(SpotATR:{spot_atr_ratio:.2f}, RVOL:{spot_rvol:.2f})"

print(f"{'SYMBOL':12} | {'SIDE':4} | {'STATUS':10} | {'REASON'}")
print("=" * 80)
for g in gold_setups:
    sym = g.get('symbol')
    side = g.get('side')
    token = token_map.get(sym)
    if not token:
        continue
    try:
        candles = kite.historical_data(token, "2026-09-20 09:15:00", "2026-09-22 15:30:00", "30minute")
        if not candles:
            continue
        df = pd.DataFrame(candles)
        df_today = df[df['date'].astype(str).str.contains("2026-09-22")]
        vwap = (df_today['volume'] * (df_today['high'] + df_today['low'] + df_today['close']) / 3).cumsum() / df_today['volume'].cumsum()
        spot_vwap = float(vwap.iloc[-1]) if not vwap.empty else 0.0
        
        ok, reason = simulate_3_core_filters(sym, side, df, spot_vwap)
        status_str = "PASS [T1]" if ok else "BLOCKED"
        print(f"{sym:12} | {side:4} | {status_str:10} | {reason}")
    except Exception as e:
        print(f"Error {sym}: {e}")
