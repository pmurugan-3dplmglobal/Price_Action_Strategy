import os
import logging
import pandas as pd
import numpy as np
from datetime import datetime as dt, timedelta, date

A_CACHE = {}

def _a_cache_key(symbol, target_date):
    return f"{symbol}|{target_date}"

def _no_pa_left(df, a_idx, ref_price, n_a, is_bull):
    """Check no price action left of anchor pattern."""
    if a_idx - n_a - 2 < 0:
        return True
    left = df.iloc[:a_idx - n_a - 1]
    if left.empty:
        return True
    if is_bull:
        return float(left['close'].min()) >= ref_price
    else:
        return float(left['close'].max()) <= ref_price

def find_swing_lows(df, window=5):
    """Find swing lows in dataframe."""
    lows = []
    for i in range(window, len(df) - window):
        w = df.iloc[i - window:i + window + 1]
        if len(w) == 2 * window + 1 and float(df.iloc[i]['low']) == float(w['low'].min()):
            lows.append(i)
    return lows

def find_swing_highs(df, window=5):
    """Find swing highs in dataframe."""
    highs = []
    for i in range(window, len(df) - window):
        w = df.iloc[i - window:i + window + 1]
        if len(w) == 2 * window + 1 and float(df.iloc[i]['high']) == float(w['high'].max()):
            highs.append(i)
    return highs

def find_pin_bars(df, pattern_type='bull'):
    """Find pin bars (hammer/shooting star)."""
    pins = []
    for i in range(1, len(df)):
        o = float(df.iloc[i]['open'])
        h = float(df.iloc[i]['high'])
        l = float(df.iloc[i]['low'])
        c = float(df.iloc[i]['close'])
        body = abs(c - o)
        rng = h - l
        if rng == 0:
            continue
        if pattern_type == 'bull':
            lower_wick = min(o, c) - l
            upper_wick = h - max(o, c)
            if lower_wick >= 2 * body and upper_wick <= 0.5 * body and c > o:
                pins.append(i)
        else:
            lower_wick = min(o, c) - l
            upper_wick = h - max(o, c)
            if upper_wick >= 2 * body and lower_wick <= 0.5 * body and c < o:
                pins.append(i)
    return pins

def find_anchor_bullish_engulfing(df):
    """Find bullish engulfing patterns."""
    eng = []
    for i in range(1, len(df)):
        o1, c1 = float(df.iloc[i-1]['open']), float(df.iloc[i-1]['close'])
        o2, c2 = float(df.iloc[i]['open']), float(df.iloc[i]['close'])
        if c1 < o1 and c2 > o2 and o2 <= c1 and c2 >= o1:
            eng.append(i)
    return eng

def find_anchor_ll_sweep(df):
    """Find bullish LL Sweep (A-B-C-D liquidity sweep pattern).

    Phase A (Sell-off): Large red candle breaks below prior swing low → LOW-2.
    Phase B (Breakout): Strong green candle closes above BENCHMARK.
    Phase C (Retest/Sweep): Red candle dips below BENCHMARK with long lower wick.
    Phase D (Trigger): Green candle opens near BENCHMARK, closes above it.

    Returns list of dicts: {idx, low2, benchmark, sl, ref_price, pattern_name}
    """
    n = len(df)
    if n < 20:
        return []

    bodies = [abs(float(df.iloc[i]['close']) - float(df.iloc[i]['open'])) for i in range(n)]
    avg_body = float(np.mean(bodies)) if bodies else 1
    swing_lows = find_swing_lows(df, window=3)

    results = []
    for low2_idx in swing_lows:
        low2 = float(df.iloc[low2_idx]['low'])

        # Phase A: Find the large red candle that started the drop (≤15 bars before LOW-2)
        phase1_idx = None
        benchmark = None
        for lookback in range(max(0, low2_idx - 15), low2_idx):
            cand = df.iloc[lookback]
            oc = float(cand['open'])
            cc = float(cand['close'])
            body = abs(cc - oc)
            if cc < oc and body > 1.5 * avg_body and float(cand['low']) >= low2:
                phase1_idx = lookback
                benchmark = cc

        if benchmark is None:
            continue

        # LOW-2 must be below the nearest prior swing low
        prior_swing_lows = [sl for sl in swing_lows if sl < low2_idx and sl >= (phase1_idx - 3)]
        if not prior_swing_lows:
            continue
        low1 = min(float(df.iloc[sl]['low']) for sl in prior_swing_lows[-3:])
        if low2 >= low1:
            continue

        # Phase B: Green candle closing above BENCHMARK (≤10 bars after LOW-2)
        pb_idx = None
        for k in range(low2_idx + 1, min(low2_idx + 10, n)):
            ck = float(df.iloc[k]['close'])
            ok = float(df.iloc[k]['open'])
            if ck > ok and ck > benchmark:
                pb_idx = k
                break
        if pb_idx is None:
            continue

        # Phase C: Red candle dipping below BENCHMARK with long lower wick (≤10 bars after B)
        pc_idx = None
        for l in range(pb_idx + 1, min(pb_idx + 10, n)):
            cand = df.iloc[l]
            o_l, c_l, h_l, lo_l = float(cand['open']), float(cand['close']), float(cand['high']), float(cand['low'])
            body_l = abs(c_l - o_l)
            rng_l = h_l - lo_l
            if rng_l == 0:
                continue
            lower_wick = min(o_l, c_l) - lo_l
            if c_l < o_l and lo_l < benchmark and lower_wick >= 2 * body_l:
                pc_idx = l
                break
        if pc_idx is None:
            continue

        # Phase D: Green candle reclaiming above BENCHMARK (≤10 bars after C)
        pd_idx = None
        for m in range(pc_idx + 1, min(pc_idx + 10, n)):
            cand = df.iloc[m]
            o_m, c_m = float(cand['open']), float(cand['close'])
            if c_m > o_m and c_m > benchmark:
                pd_idx = m
                break
        if pd_idx is None:
            continue

        results.append({
            "idx": pd_idx,
            "low2": low2,
            "benchmark": benchmark,
            "sl": low2 - 1,
            "ref_price": float(df.iloc[pd_idx]['open']),
            "pattern_name": "BULL_LL_SWEEP"
        })

    return results

def find_anchor_hammer_baby(df):
    """Find hammer/baby pattern (bullish)."""
    hammers = []
    for i in range(1, len(df)):
        o = float(df.iloc[i]['open'])
        h = float(df.iloc[i]['high'])
        l = float(df.iloc[i]['low'])
        c = float(df.iloc[i]['close'])
        body = abs(c - o)
        rng = h - l
        if rng == 0:
            continue
        lower_wick = min(o, c) - l
        upper_wick = h - max(o, c)
        if lower_wick >= 2 * body and upper_wick <= 0.3 * rng and c > o:
            hammers.append(i)
    return hammers

def find_anchor_bullish_harami(df):
    """Find bullish harami pattern."""
    harami = []
    for i in range(1, len(df)):
        o1, c1 = float(df.iloc[i-1]['open']), float(df.iloc[i-1]['close'])
        o2, c2 = float(df.iloc[i]['open']), float(df.iloc[i]['close'])
        if c1 < o1 and c2 > o2 and o2 > c1 and c2 < o1:
            harami.append(i)
    return harami

def find_anchor_bearish_engulfing(df):
    """Find bearish engulfing patterns."""
    eng = []
    for i in range(1, len(df)):
        o1, c1 = float(df.iloc[i-1]['open']), float(df.iloc[i-1]['close'])
        o2, c2 = float(df.iloc[i]['open']), float(df.iloc[i]['close'])
        if c1 > o1 and c2 < o2 and o2 >= c1 and c2 <= o1:
            eng.append(i)
    return eng

def find_anchor_hh_sweep(df):
    """Find bearish HH Sweep (A-B-C-D liquidity sweep pattern, bearish mirror).

    Phase A (Rally): Large green candle breaks above prior swing high → HIGH-2.
    Phase B (Breakout): Strong red candle closes below BENCHMARK.
    Phase C (Retest/Sweep): Green candle rallies above BENCHMARK with long upper wick.
    Phase D (Trigger): Red candle opens near BENCHMARK, closes below it.

    Returns list of dicts: {idx, high2, benchmark, sl, ref_price, pattern_name}
    """
    n = len(df)
    if n < 20:
        return []

    bodies = [abs(float(df.iloc[i]['close']) - float(df.iloc[i]['open'])) for i in range(n)]
    avg_body = float(np.mean(bodies)) if bodies else 1
    swing_highs = find_swing_highs(df, window=3)

    results = []
    for high2_idx in swing_highs:
        high2 = float(df.iloc[high2_idx]['high'])

        # Phase A: Find the large green candle that started the rally (≤15 bars before HIGH-2)
        phase1_idx = None
        benchmark = None
        for lookback in range(max(0, high2_idx - 15), high2_idx):
            cand = df.iloc[lookback]
            oc = float(cand['open'])
            cc = float(cand['close'])
            body = abs(cc - oc)
            if cc > oc and body > 1.5 * avg_body and float(cand['high']) <= high2:
                phase1_idx = lookback
                benchmark = cc

        if benchmark is None:
            continue

        # HIGH-2 must be above the nearest prior swing high
        prior_swing_highs = [sh for sh in swing_highs if sh < high2_idx and sh >= (phase1_idx - 3)]
        if not prior_swing_highs:
            continue
        high1 = max(float(df.iloc[sh]['high']) for sh in prior_swing_highs[-3:])
        if high2 <= high1:
            continue

        # Phase B: Red candle closing below BENCHMARK (≤10 bars after HIGH-2)
        pb_idx = None
        for k in range(high2_idx + 1, min(high2_idx + 10, n)):
            ck = float(df.iloc[k]['close'])
            ok = float(df.iloc[k]['open'])
            if ck < ok and ck < benchmark:
                pb_idx = k
                break
        if pb_idx is None:
            continue

        # Phase C: Green candle rallying above BENCHMARK with long upper wick (≤10 bars after B)
        pc_idx = None
        for l in range(pb_idx + 1, min(pb_idx + 10, n)):
            cand = df.iloc[l]
            o_l, c_l, h_l, lo_l = float(cand['open']), float(cand['close']), float(cand['high']), float(cand['low'])
            body_l = abs(c_l - o_l)
            rng_l = h_l - lo_l
            if rng_l == 0:
                continue
            upper_wick = h_l - max(o_l, c_l)
            if c_l > o_l and h_l > benchmark and upper_wick >= 2 * body_l:
                pc_idx = l
                break
        if pc_idx is None:
            continue

        # Phase D: Red candle closing below BENCHMARK (≤10 bars after C)
        pd_idx = None
        for m in range(pc_idx + 1, min(pc_idx + 10, n)):
            cand = df.iloc[m]
            o_m, c_m = float(cand['open']), float(cand['close'])
            if c_m < o_m and c_m < benchmark:
                pd_idx = m
                break
        if pd_idx is None:
            continue

        results.append({
            "idx": pd_idx,
            "high2": high2,
            "benchmark": benchmark,
            "sl": high2 + 1,
            "ref_price": float(df.iloc[pd_idx]['open']),
            "pattern_name": "BEAR_HH_SWEEP"
        })

    return results

def find_anchor_shooting_star(df):
    """Find shooting star pattern (bearish)."""
    stars = []
    for i in range(1, len(df)):
        o = float(df.iloc[i]['open'])
        h = float(df.iloc[i]['high'])
        l = float(df.iloc[i]['low'])
        c = float(df.iloc[i]['close'])
        body = abs(c - o)
        rng = h - l
        if rng == 0:
            continue
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        if upper_wick >= 2 * body and lower_wick <= 0.3 * rng and c < o:
            stars.append(i)
    return stars

def find_anchor_bearish_harami(df):
    """Find bearish harami pattern."""
    harami = []
    for i in range(1, len(df)):
        o1, c1 = float(df.iloc[i-1]['open']), float(df.iloc[i-1]['close'])
        o2, c2 = float(df.iloc[i]['open']), float(df.iloc[i]['close'])
        if c1 > o1 and c2 < o2 and o2 < c1 and c2 > o1:
            harami.append(i)
    return harami

def find_swing_double_bottom(df):
    """Find double bottom pattern."""
    bottoms = []
    lows = find_swing_lows(df, window=10)
    for i in range(len(lows) - 1):
        idx1, idx2 = lows[i], lows[i + 1]
        if abs(idx2 - idx1) < 5:
            continue
        l1 = float(df.iloc[idx1]['low'])
        l2 = float(df.iloc[idx2]['low'])
        if abs(l1 - l2) / max(l1, l2) < 0.02:
            mid_high = float(df.iloc[idx1:idx2]['high'].max())
            if float(df.iloc[idx2]['close']) > mid_high:
                bottoms.append(idx2)
    return bottoms

def find_swing_double_top(df):
    """Find double top pattern."""
    tops = []
    highs = find_swing_highs(df, window=10)
    for i in range(len(highs) - 1):
        idx1, idx2 = highs[i], highs[i + 1]
        if abs(idx2 - idx1) < 5:
            continue
        h1 = float(df.iloc[idx1]['high'])
        h2 = float(df.iloc[idx2]['high'])
        if abs(h1 - h2) / max(h1, h2) < 0.02:
            mid_low = float(df.iloc[idx1:idx2]['low'].min())
            if float(df.iloc[idx2]['close']) < mid_low:
                tops.append(idx2)
    return tops

def detect_and_cache_a(df_anchor, symbol, target_date, pattern_type='bull'):
    """Detect and cache A-patterns (anchor patterns) for a symbol."""
    cache_key = _a_cache_key(symbol, target_date)
    if cache_key in A_CACHE:
        return A_CACHE[cache_key]

    result = {}
    if pattern_type == 'bull':
        anchors = []
        for name, func in [
            ('BULL_ENGULF', find_anchor_bullish_engulfing),
            ('BULL_LL_SWEEP', find_anchor_ll_sweep),
            ('BULL_HAMMER', find_anchor_hammer_baby),
            ('BULL_HARAMI', find_anchor_bullish_harami),
            ('BULL_DBL_BOT', find_swing_double_bottom),
        ]:
            results = func(df_anchor)
            for r in results:
                if isinstance(r, dict):
                    anchors.append((r["idx"], r.get("pattern_name", name), r))
                else:
                    anchors.append((r, name, {}))

        if anchors:
            a_idx, pattern_name, extra = anchors[-1]
            a = df_anchor.iloc[a_idx]
            if extra:
                benchmark = extra["benchmark"]
                sl = extra["sl"]
                ref_price = extra["ref_price"]
            else:
                ref_price = float(a['open'])
                sl = float(a['low']) - 1
                benchmark = float(a['high'])

            if _no_pa_left(df_anchor, a_idx, ref_price, 0, True):
                t1, t2, t3 = find_profit_targets_negation(df_anchor, benchmark, benchmark, 'bull')
                result = {
                    "pattern_name": pattern_name,
                    "needs_bcd": True,
                    "a_idx": a_idx,
                    "a_ts": a['date'],
                    "benchmark": benchmark,
                    "SL": sl,
                    "ref_price": ref_price,
                    "t1": t1, "t2": t2, "t3": t3
                }
                A_CACHE[cache_key] = result
                logging.info(f"ANCHOR CACHED: {symbol} | {pattern_name} | Benchmark: {benchmark:.2f} | SL: {sl:.2f} | T1: {t1} | T2: {t2} | T3: {t3}")
                return result
    else:
        anchors = []
        for name, func in [
            ('BEAR_ENGULF', find_anchor_bearish_engulfing),
            ('BEAR_HH_SWEEP', find_anchor_hh_sweep),
            ('BEAR_SHOOTING', find_anchor_shooting_star),
            ('BEAR_HARAMI', find_anchor_bearish_harami),
            ('BEAR_DBL_TOP', find_swing_double_top),
        ]:
            results = func(df_anchor)
            for r in results:
                if isinstance(r, dict):
                    anchors.append((r["idx"], r.get("pattern_name", name), r))
                else:
                    anchors.append((r, name, {}))

        if anchors:
            a_idx, pattern_name, extra = anchors[-1]
            a = df_anchor.iloc[a_idx]
            if extra:
                benchmark = extra["benchmark"]
                sl = extra["sl"]
                ref_price = extra["ref_price"]
            else:
                ref_price = float(a['open'])
                sl = float(a['high']) + 1
                benchmark = float(a['low'])

            if _no_pa_left(df_anchor, a_idx, ref_price, 0, False):
                t1, t2, t3 = find_profit_targets_negation(df_anchor, benchmark, benchmark, 'bear')
                result = {
                    "pattern_name": pattern_name,
                    "needs_bcd": True,
                    "a_idx": a_idx,
                    "a_ts": a['date'],
                    "benchmark": benchmark,
                    "SL": sl,
                    "ref_price": ref_price,
                    "t1": t1, "t2": t2, "t3": t3
                }
                A_CACHE[cache_key] = result
                logging.info(f"ANCHOR CACHED: {symbol} | {pattern_name} | Benchmark: {benchmark:.2f} | SL: {sl:.2f} | T1: {t1} | T2: {t2} | T3: {t3}")
                return result

    A_CACHE[cache_key] = None
    return None

def find_bcd_forward(df_entry, a_ts, benchmark, pattern_type='bull'):
    """Find BCD pattern (Breakout/Continuation/Deceleration) forward from anchor."""
    if df_entry.empty:
        return None
    
    a_dt = pd.Timestamp(a_ts)
    df = df_entry[df_entry['date'] > a_dt].copy()
    if df.empty:
        return None
    
    if pattern_type == 'bull':
        for i in range(len(df)):
            c = float(df.iloc[i]['close'])
            if c > benchmark:
                return df.iloc[i]
    else:
        for i in range(len(df)):
            c = float(df.iloc[i]['close'])
            if c < benchmark:
                return df.iloc[i]
    return None

def find_profit_targets_negation(df_hist, entry_close, benchmark=None, pattern_type='bull'):
    """Find T1, T2, T3 using Negation Theory with S/R fallback."""
    hist = df_hist.copy()
    levels = []
    
    if pattern_type == 'bull':
        for i in range(len(hist) - 3, 2, -1):
            w = hist.iloc[i-2:i+3]
            if len(w) == 5 and float(hist.iloc[i]['high']) == float(w['high'].max()):
                h = float(hist.iloc[i]['high'])
                if h > entry_close and h not in levels:
                    levels.append(h)
        for i in range(len(hist) - 1, 2, -1):
            if (float(hist.iloc[i]['close']) > float(hist.iloc[i]['open']) and
                float(hist.iloc[i-1]['close']) < float(hist.iloc[i-1]['open']) and
                float(hist.iloc[i]['open']) <= float(hist.iloc[i-1]['close']) and
                float(hist.iloc[i]['close']) > float(hist.iloc[i-1]['high'])):
                h = float(hist.iloc[i]['high'])
                if h > entry_close and h not in levels:
                    levels.append(h)
        mh = float(hist['high'].max())
        if mh > entry_close and mh not in levels:
            levels.append(mh)
        levels = sorted(levels)
    else:
        for i in range(len(hist) - 3, 2, -1):
            w = hist.iloc[i-2:i+3]
            if len(w) == 5 and float(hist.iloc[i]['low']) == float(w['low'].min()):
                l = float(hist.iloc[i]['low'])
                if l < entry_close and l not in levels:
                    levels.append(l)
        for i in range(len(hist) - 1, 2, -1):
            if (float(hist.iloc[i]['close']) < float(hist.iloc[i]['open']) and
                float(hist.iloc[i-1]['close']) > float(hist.iloc[i-1]['open']) and
                float(hist.iloc[i]['open']) >= float(hist.iloc[i-1]['close']) and
                float(hist.iloc[i]['close']) < float(hist.iloc[i-1]['low'])):
                l = float(hist.iloc[i]['low'])
                if l < entry_close and l not in levels:
                    levels.append(l)
        ml = float(hist['low'].min())
        if ml < entry_close and ml not in levels:
            levels.append(ml)
        levels = sorted(levels, reverse=True)
    
    t1 = levels[0] if len(levels) > 0 else None
    t2 = levels[1] if len(levels) > 1 else None
    t3 = levels[2] if len(levels) > 2 else None
    
    return t1, t2, t3

def calculate_rr(entry, sl, target, pattern_type='bull'):
    """Calculate risk-reward ratio."""
    if pattern_type == 'bull':
        risk = entry - sl
        reward = target - entry
    else:
        risk = sl - entry
        reward = entry - target
    if risk <= 0:
        return 0
    return round(reward / risk, 2)

def _trade_rr(trade, side):
    """Calculate RR for a trade dict."""
    entry = trade.get("Close") or trade.get("Entry") or 0
    sl = trade.get("SL") or 0
    t1 = trade.get("T1") or trade.get("t1")
    if entry == 0 or sl == 0 or t1 is None:
        return 0
    if side == 'CE':
        risk = entry - sl
        reward = t1 - entry
    else:
        risk = sl - entry
        reward = entry - t1
    return round(reward / risk, 2) if risk > 0 else 0