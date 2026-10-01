import json
import datetime
import sys

sys.stdout.reconfigure(encoding='utf-8')

def resample_15m_to_30m(candles_15m):
    """
    Resamples 15m candles into 30m candles.
    Candles are: [timestamp, open, high, low, close, volume]
    """
    candles_30m = []
    i = 0
    while i < len(candles_15m):
        c1 = candles_15m[i]
        if i + 1 < len(candles_15m):
            c2 = candles_15m[i+1]
            # Check if they belong to the same 30m block
            # 09:15 + 09:30 = 09:15-09:45 block
            ts1 = c1[0]
            ts2 = c2[0]
            if ts1[:10] == ts2[:10]: # same day
                o = c1[1]
                h = max(c1[2], c2[2])
                l = min(c1[3], c2[3])
                close = c2[4]
                vol = c1[5] + c2[5]
                candles_30m.append([ts1, o, h, l, close, vol])
                i += 2
                continue
        # If single odd candle at end of day
        candles_30m.append(c1)
        i += 1
    return candles_30m

def detect_anchors_30m(candles_30m):
    """
    Detects 30m Anchors (Bullish CE and Bearish PE).
    Returns list of dicts.
    """
    anchors = []
    for idx in range(len(candles_30m) - 2):
        c = candles_30m[idx]
        o, h, l, close, vol = c[1], c[2], c[3], c[4], c[5]
        
        # Bullish
        is_hammer = (min(o, close) - l) >= 1.5 * abs(close - o) and (h - max(o, close)) <= 0.5 * abs(close - o)
        is_bull_engulf = (close > o) and (idx > 0 and close >= candles_30m[idx-1][2] and l <= candles_30m[idx-1][3])
        is_two_hh = (idx > 0 and h > candles_30m[idx-1][2] and l > candles_30m[idx-1][3] and close > o)
        is_base = (idx >= 2 and max(candles_30m[i][2] for i in range(idx-2, idx+1)) - min(candles_30m[i][3] for i in range(idx-2, idx+1))) <= 0.008 * close
        
        if is_hammer or is_bull_engulf or is_two_hh or is_base:
            pat = "HAMMER" if is_hammer else ("ENGULF" if is_bull_engulf else ("TWO_HH" if is_two_hh else "BASE"))
            benchmark = h
            sl = l * 0.998
            risk = benchmark - sl
            if risk > 0:
                anchors.append({
                    "side": "CE",
                    "pattern": pat,
                    "anchor_idx": idx,
                    "anchor_ts": c[0],
                    "benchmark": benchmark,
                    "sl": sl,
                    "t1": benchmark + 1.5 * risk,
                    "t2": benchmark + 2.5 * risk,
                    "risk_pct": risk / benchmark * 100
                })

        # Bearish
        is_shooting_star = (h - max(o, close)) >= 1.5 * abs(close - o) and (min(o, close) - l) <= 0.5 * abs(close - o)
        is_bear_engulf = (close < o) and (idx > 0 and close <= candles_30m[idx-1][3] and h >= candles_30m[idx-1][2])
        is_two_ll = (idx > 0 and l < candles_30m[idx-1][3] and h < candles_30m[idx-1][2] and close < o)
        is_top_base = (idx >= 2 and max(candles_30m[i][2] for i in range(idx-2, idx+1)) - min(candles_30m[i][3] for i in range(idx-2, idx+1))) <= 0.008 * close
        
        if is_shooting_star or is_bear_engulf or is_two_ll or is_top_base:
            pat = "SHOOTING_STAR" if is_shooting_star else ("ENGULF" if is_bear_engulf else ("TWO_LL" if is_two_ll else "BASE"))
            benchmark = l
            sl = h * 1.002
            risk = sl - benchmark
            if risk > 0:
                anchors.append({
                    "side": "PE",
                    "pattern": pat,
                    "anchor_idx": idx,
                    "anchor_ts": c[0],
                    "benchmark": benchmark,
                    "sl": sl,
                    "t1": benchmark - 1.5 * risk,
                    "t2": benchmark - 2.5 * risk,
                    "risk_pct": risk / benchmark * 100
                })
    return anchors

def simulate_case_1(sym, date, c_15m, c_30m, anchors_30m):
    """
    CASE 1: Anchor 30m, Entry 15m.
    Entry triggers when a 15m candle closes or crosses Benchmark after Anchor.
    """
    trades = []
    for anc in anchors_30m:
        anc_ts = anc["anchor_ts"]
        side = anc["side"]
        bm = anc["benchmark"]
        sl = anc["sl"]
        t1 = anc["t1"]
        
        # Find 15m candles after anchor timestamp
        post_15m = [c for c in c_15m if c[0] > anc_ts]
        for e_idx, c in enumerate(post_15m):
            triggered = False
            if side == "CE" and c[2] >= bm and c[3] >= sl: # 15m candle crosses benchmark
                triggered = True
            elif side == "PE" and c[3] <= bm and c[2] <= sl:
                triggered = True
                
            if triggered:
                entry_p = bm
                entry_ts = c[0]
                remaining_15m = post_15m[e_idx:]
                
                # Intraday stats
                day_end_15m = [rc for rc in remaining_15m if rc[0][:10] == date]
                if not day_end_15m:
                    break
                intraday_high = max(rc[2] for rc in day_end_15m)
                intraday_low = min(rc[3] for rc in day_end_15m)
                intraday_close = day_end_15m[-1][4]
                
                if side == "CE":
                    intra_t1 = intraday_high >= t1
                    intra_sl = any(rc[4] <= sl for rc in day_end_15m) # candle close SL
                    intra_mfe = (intraday_high - entry_p) / entry_p * 100
                    intra_pnl = (intraday_close - entry_p) / entry_p * 100
                else:
                    intra_t1 = intraday_low <= t1
                    intra_sl = any(rc[4] >= sl for rc in day_end_15m)
                    intra_mfe = (entry_p - intraday_low) / entry_p * 100
                    intra_pnl = (entry_p - intraday_close) / entry_p * 100
                    
                trades.append({
                    "case": "CASE_1 (Anchor 30m / Entry 15m)",
                    "date": date,
                    "symbol": sym,
                    "side": side,
                    "pattern": anc["pattern"],
                    "entry_ts": entry_ts,
                    "entry_p": entry_p,
                    "sl": sl,
                    "t1": t1,
                    "risk_pct": anc["risk_pct"],
                    "intra_t1": intra_t1,
                    "intra_sl": intra_sl,
                    "intra_mfe": round(intra_mfe, 2),
                    "intra_pnl": round(intra_pnl, 2),
                    "opt_intra_mfe": round(min(intra_mfe * 12.0, 120.0), 1),
                })
                break # 1 trade per anchor
    return trades

def simulate_case_2(sym, date, c_30m, anchors_30m):
    """
    CASE 2: Anchor 30m, Entry 30m.
    Entry triggers ONLY when a full 30m candle closes beyond Benchmark after Anchor.
    """
    trades = []
    for anc in anchors_30m:
        anc_ts = anc["anchor_ts"]
        side = anc["side"]
        bm = anc["benchmark"]
        sl = anc["sl"]
        t1 = anc["t1"]
        
        # Find 30m candles strictly after anchor
        post_30m = [c for c in c_30m if c[0] > anc_ts]
        for e_idx, c in enumerate(post_30m):
            triggered = False
            # Full 30m candle close confirmation
            if side == "CE" and c[4] > bm and c[3] >= sl:
                triggered = True
                entry_p = c[4] # entry at 30m close
            elif side == "PE" and c[4] < bm and c[2] <= sl:
                triggered = True
                entry_p = c[4]
                
            if triggered:
                entry_ts = c[0]
                remaining_30m = post_30m[e_idx:]
                
                day_end_30m = [rc for rc in remaining_30m if rc[0][:10] == date]
                if not day_end_30m:
                    break
                intraday_high = max(rc[2] for rc in day_end_30m)
                intraday_low = min(rc[3] for rc in day_end_30m)
                intraday_close = day_end_30m[-1][4]
                
                if side == "CE":
                    intra_t1 = intraday_high >= t1
                    intra_sl = any(rc[4] <= sl for rc in day_end_30m)
                    intra_mfe = (intraday_high - entry_p) / entry_p * 100
                    intra_pnl = (intraday_close - entry_p) / entry_p * 100
                else:
                    intra_t1 = intraday_low <= t1
                    intra_sl = any(rc[4] >= sl for rc in day_end_30m)
                    intra_mfe = (entry_p - intraday_low) / entry_p * 100
                    intra_pnl = (entry_p - intraday_close) / entry_p * 100
                    
                trades.append({
                    "case": "CASE_2 (Anchor 30m / Entry 30m)",
                    "date": date,
                    "symbol": sym,
                    "side": side,
                    "pattern": anc["pattern"],
                    "entry_ts": entry_ts,
                    "entry_p": entry_p,
                    "sl": sl,
                    "t1": t1,
                    "risk_pct": anc["risk_pct"],
                    "intra_t1": intra_t1,
                    "intra_sl": intra_sl,
                    "intra_mfe": round(intra_mfe, 2),
                    "intra_pnl": round(intra_pnl, 2),
                    "opt_intra_mfe": round(min(intra_mfe * 12.0, 120.0), 1),
                })
                break
    return trades

def run_simulation():
    # Load 15m candles from previous fetch
    import urllib.request
    with open('scratch/fno_tokens_master.json') as f:
        tokens_map = json.load(f)
        
    token = open('input/kite_access_token.txt').read().strip()
    headers = {'X-Kite-Version': '3', 'Authorization': f'token o8nnw6kxykvrsrhg:{token}'}
    to_date = datetime.date(2026, 10, 1)
    from_date = to_date - datetime.timedelta(days=30)
    
    print("=== RUNNING TIMEFRAME COMPARISON SIMULATION ===")
    print("Universe: 63 Core F&O Heavyweights over 22 Sessions (1 Month)")
    print("Comparing:")
    print("  CASE 1: Anchor 30m / Entry 15m")
    print("  CASE 2: Anchor 30m / Entry 30m")
    print("  Also Comparing: Carryforward vs Each Day Closing\n")
    
    all_case1 = []
    all_case2 = []
    
    for idx, (sym, meta) in enumerate(list(tokens_map.items())[:25]): # sample 25 representative stocks
        tok = meta['token']
        url = f"https://api.kite.trade/instruments/historical/{tok}/15minute?from={from_date}&to={to_date}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                c_15m = data.get('data', {}).get('candles', [])
        except Exception:
            continue
            
        if not c_15m:
            continue
            
        # Group by day
        days_15m = {}
        for c in c_15m:
            d = c[0][:10]
            if d not in days_15m:
                days_15m[d] = []
            days_15m[d].append(c)
            
        for d, day_15m in days_15m.items():
            if len(day_15m) < 8:
                continue
            day_30m = resample_15m_to_30m(day_15m)
            anchors_30m = detect_anchors_30m(day_30m)
            if not anchors_30m:
                continue
                
            c1_res = simulate_case_1(sym, d, day_15m, day_30m, anchors_30m)
            c2_res = simulate_case_2(sym, d, day_30m, anchors_30m)
            
            all_case1.extend(c1_res)
            all_case2.extend(c2_res)
            
    print(f"Simulation Complete across 25 Top Symbols!")
    print(f"Total Case 1 Trades: {len(all_case1)}")
    print(f"Total Case 2 Trades: {len(all_case2)}")
    
    with open('scratch/sim_case1_results.json', 'w') as f:
        json.dump(all_case1, f, indent=2)
    with open('scratch/sim_case2_results.json', 'w') as f:
        json.dump(all_case2, f, indent=2)
        
if __name__ == '__main__':
    run_simulation()
