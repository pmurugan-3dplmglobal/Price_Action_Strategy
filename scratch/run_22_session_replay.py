import urllib.request
import json
import datetime
import time
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

token = open('input/kite_access_token.txt').read().strip()
api_key = 'o8nnw6kxykvrsrhg'
headers = {
    'X-Kite-Version': '3',
    'Authorization': f'token {api_key}:{token}'
}

def fetch_candles(inst_token, from_date, to_date):
    url = f"https://api.kite.trade/instruments/historical/{inst_token}/15minute?from={from_date}&to={to_date}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data.get('data', {}).get('candles', [])
    except Exception as e:
        time.sleep(0.5)
        return []

def detect_setups_for_day(sym, date_str, day_candles):
    """
    Evaluates 15m intraday candles for a symbol on a specific date.
    Detects Bullish (CE) and Bearish (PE) Anchor -> BCD setups.
    """
    if len(day_candles) < 8:
        return []
    
    setups = []
    
    # 1. Bullish Setup Detection (CE)
    # Search for Point A (Anchor) in morning candles (candles 0 to 6)
    for a_idx in range(len(day_candles) - 5):
        c = day_candles[a_idx]
        o, h, l, close, vol = c[1], c[2], c[3], c[4], c[5]
        
        # Bullish Engulfing or Hammer or Base
        is_hammer = (min(o, close) - l) >= 1.5 * abs(close - o) and (h - max(o, close)) <= 0.5 * abs(close - o)
        is_bull_engulf = (close > o) and (a_idx > 0 and close >= day_candles[a_idx-1][2] and l <= day_candles[a_idx-1][3])
        is_two_hh = (a_idx > 0 and h > day_candles[a_idx-1][2] and l > day_candles[a_idx-1][3] and close > o)
        is_base = (a_idx >= 2 and max(day_candles[i][2] for i in range(a_idx-2, a_idx+1)) - min(day_candles[i][3] for i in range(a_idx-2, a_idx+1))) <= 0.008 * close
        
        pattern = None
        if is_hammer:
            pattern = "HAMMER_ABCD"
        elif is_bull_engulf:
            pattern = "BULL_ENGULF"
        elif is_two_hh:
            pattern = "TWO_HIGHER_HIGHS"
        elif is_base:
            pattern = "BASE_ABCD"
            
        if pattern:
            anchor_h = h
            anchor_l = l
            benchmark = anchor_h
            sl = anchor_l * 0.998 # Buffer
            risk = benchmark - sl
            if risk <= 0:
                continue
            t1 = benchmark + 1.5 * risk
            t2 = benchmark + 2.5 * risk
            
            # Look for Point B, C, D in subsequent candles
            for d_idx in range(a_idx + 1, len(day_candles)):
                dc = day_candles[d_idx]
                d_close = dc[4]
                d_high = dc[2]
                
                # Point D Trigger: candle breaks benchmark
                if d_high >= benchmark and dc[3] >= sl:
                    # Valid trigger!
                    entry_p = benchmark
                    entry_time = dc[0][11:16]
                    
                    # Track post-entry performance
                    future_candles = day_candles[d_idx:]
                    post_high = max(fc[2] for fc in future_candles)
                    post_low = min(fc[3] for fc in future_candles)
                    close_p = day_candles[-1][4]
                    
                    mfe_pct = (post_high - entry_p) / entry_p * 100
                    mae_pct = (post_low - entry_p) / entry_p * 100
                    t1_hit = post_high >= t1
                    
                    # Spot SL check
                    sl_hit_wick = post_low <= sl
                    sl_hit_close = any(fc[4] <= sl for fc in future_candles)
                    
                    # Estimate Option Expansion (Delta ~0.50 for ATM)
                    opt_mfe_pct = mfe_pct * 12.0 # ~12x leverage for 0.5 delta option
                    opt_mfe_pct = min(opt_mfe_pct, 120.0) # cap at 120%
                    
                    setups.append({
                        "date": date_str,
                        "symbol": sym,
                        "side": "CE",
                        "pattern": pattern,
                        "anchor_time": c[0][11:16],
                        "entry_time": entry_time,
                        "entry": round(entry_p, 2),
                        "sl": round(sl, 2),
                        "t1": round(t1, 2),
                        "risk_pct": round(risk / entry_p * 100, 2),
                        "spot_mfe_pct": round(mfe_pct, 2),
                        "spot_mae_pct": round(mae_pct, 2),
                        "opt_peak_gain_pct": round(opt_mfe_pct, 1),
                        "t1_hit": t1_hit,
                        "sl_hit_close": sl_hit_close,
                        "sl_hit_wick": sl_hit_wick,
                        "saved_by_spot_guard": (sl_hit_wick and not sl_hit_close and t1_hit)
                    })
                    break # Take first trigger
            if len(setups) > 0 and setups[-1]["side"] == "CE":
                break

    # 2. Bearish Setup Detection (PE)
    for a_idx in range(len(day_candles) - 5):
        c = day_candles[a_idx]
        o, h, l, close, vol = c[1], c[2], c[3], c[4], c[5]
        
        is_shooting_star = (h - max(o, close)) >= 1.5 * abs(close - o) and (min(o, close) - l) <= 0.5 * abs(close - o)
        is_bear_engulf = (close < o) and (a_idx > 0 and close <= day_candles[a_idx-1][3] and h >= day_candles[a_idx-1][2])
        is_two_ll = (a_idx > 0 and l < day_candles[a_idx-1][3] and h < day_candles[a_idx-1][2] and close < o)
        is_top_base = (a_idx >= 2 and max(day_candles[i][2] for i in range(a_idx-2, a_idx+1)) - min(day_candles[i][3] for i in range(a_idx-2, a_idx+1))) <= 0.008 * close
        
        pattern = None
        if is_shooting_star:
            pattern = "SHOOTING_STAR_ABCD"
        elif is_bear_engulf:
            pattern = "BEAR_ENGULF"
        elif is_two_ll:
            pattern = "TWO_LOWER_LOWS"
        elif is_top_base:
            pattern = "BASE_DISTRIBUTION"
            
        if pattern:
            anchor_h = h
            anchor_l = l
            benchmark = anchor_l
            sl = anchor_h * 1.002 # Buffer
            risk = sl - benchmark
            if risk <= 0:
                continue
            t1 = benchmark - 1.5 * risk
            t2 = benchmark - 2.5 * risk
            
            for d_idx in range(a_idx + 1, len(day_candles)):
                dc = day_candles[d_idx]
                d_low = dc[3]
                
                # Breakdown Trigger
                if d_low <= benchmark and dc[2] <= sl:
                    entry_p = benchmark
                    entry_time = dc[0][11:16]
                    
                    future_candles = day_candles[d_idx:]
                    post_high = max(fc[2] for fc in future_candles)
                    post_low = min(fc[3] for fc in future_candles)
                    
                    mfe_pct = (entry_p - post_low) / entry_p * 100
                    mae_pct = (entry_p - post_high) / entry_p * 100
                    t1_hit = post_low <= t1
                    
                    sl_hit_wick = post_high >= sl
                    sl_hit_close = any(fc[4] >= sl for fc in future_candles)
                    
                    opt_mfe_pct = mfe_pct * 12.0
                    opt_mfe_pct = min(opt_mfe_pct, 120.0)
                    
                    setups.append({
                        "date": date_str,
                        "symbol": sym,
                        "side": "PE",
                        "pattern": pattern,
                        "anchor_time": c[0][11:16],
                        "entry_time": entry_time,
                        "entry": round(entry_p, 2),
                        "sl": round(sl, 2),
                        "t1": round(t1, 2),
                        "risk_pct": round(risk / entry_p * 100, 2),
                        "spot_mfe_pct": round(mfe_pct, 2),
                        "spot_mae_pct": round(mae_pct, 2),
                        "opt_peak_gain_pct": round(opt_mfe_pct, 1),
                        "t1_hit": t1_hit,
                        "sl_hit_close": sl_hit_close,
                        "sl_hit_wick": sl_hit_wick,
                        "saved_by_spot_guard": (sl_hit_wick and not sl_hit_close and t1_hit)
                    })
                    break
            if len(setups) > 0 and setups[-1]["side"] == "PE":
                break

    return setups

def run_replay():
    with open('scratch/fno_tokens_master.json') as f:
        tokens_map = json.load(f)
        
    to_date = datetime.date(2026, 10, 1)
    from_date = to_date - datetime.timedelta(days=30)
    
    print(f"=== LAUNCHING 22-SESSION KITE HISTORICAL REPLAY ({from_date} to {to_date}) ===")
    print(f"Target Universe: {len(tokens_map)} Core F&O Stocks\n")
    
    all_setups = []
    symbols = list(tokens_map.keys())
    
    for idx, sym in enumerate(symbols):
        tok = tokens_map[sym]['token']
        candles = fetch_candles(tok, from_date, to_date)
        if not candles:
            continue
            
        # Group by date
        days_map = {}
        for c in candles:
            d = c[0][:10]
            if d not in days_map:
                days_map[d] = []
            days_map[d].append(c)
            
        # Analyze each session
        sym_setups = 0
        for d, day_candles in days_map.items():
            res = detect_setups_for_day(sym, d, day_candles)
            if res:
                all_setups.extend(res)
                sym_setups += len(res)
                
        print(f"[{idx+1:02d}/{len(symbols):02d}] {sym:<12} | Fetched {len(candles):<4} candles | Detected {sym_setups} setups")
        time.sleep(0.12) # Rate limit friendly (3 requests/sec)
        
    print(f"\nReplay Complete! Total Setups Detected across 22 Sessions: {len(all_setups)}")
    with open('scratch/replay_22_sessions_results.json', 'w', encoding='utf-8') as f:
        json.dump(all_setups, f, indent=2)
    print("Saved results to scratch/replay_22_sessions_results.json")

if __name__ == '__main__':
    run_replay()
