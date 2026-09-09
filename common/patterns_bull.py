"""
Bullish price action pattern detectors: 5 anchor patterns (engulfing, LL sweep,
hammer baby, harami, two higher highs), A-B-C-D breakout scanner, and trend
continuation re-entry (Page 16).
Extracted from trading_core.py (2026-08-11).
"""
import os, sys
COMMON_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(COMMON_DIR)
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import logging
import pandas as pd
from datetime import datetime as dt

from targets import (
    find_profit_targets, check_left_side_rule,
    calculate_sl_buffer, calculate_position_size, calc_rr
)
from timeframe_utils import get_adaptive_lookback, resample_timeframe, trading_days_between, is_live_candle_near_close, get_tf_minutes
from swing_detection import (
    is_parabolic_arch_enhanced,
    extract_swing_pivots,
    validate_parabolic_cascade_structure,
    detect_parabolic_multi_swings,
    calculate_twap_c_stability,
    calculate_vcp_metrics
)

def clean_timestamp(ts):
    """Clean ISO timestamp string by stripping timezone offsets (+05:30), seconds, and T separator."""
    if not ts or ts == '-':
        return ""
    s = str(ts).split('+')[0].split('.')[0].replace('T', ' ').strip()
    p = s.split(' ')
    if len(p) == 2:
        date_part, time_part = p[0], p[1]
        t_parts = time_part.split(':')
        if len(t_parts) >= 2:
            return f"{date_part} {t_parts[0]}:{t_parts[1]}"
    return s

# ──────────────────────────────────────────────
#  ANCHOR (A-FORMATION) DETECTION — 5 PATTERNS
# ──────────────────────────────────────────────

def find_anchor_bullish_engulfing(df):
    """A = bullish engulfing candle. Bearish candle-1, then bullish candle that wraps its body+wick."""
    if len(df) < 2:
        return None
    bearish_candle, bull_anchor = df.iloc[-2], df.iloc[-1]
    if not (float(bearish_candle['close']) < float(bearish_candle['open'])):
        return None
    if not (float(bull_anchor['close']) > float(bull_anchor['open'])):
        return None
    if not (float(bull_anchor['open']) <= float(bearish_candle['close']) and float(bull_anchor['close']) > float(bearish_candle['high'])):
        return None
    a_high = float(bull_anchor['high'])
    a_low = float(bull_anchor['low'])
    anchor_close = float(bull_anchor['close'])
    sl_val = calculate_sl_buffer(a_low, side="BULL")
    return {
        "Pattern": "BULL_A_ABCD_Engulf",
        "Close": anchor_close,
        "SL": sl_val,
        "AnchorHigh": a_high,
        "AnchorLow": a_low,
        "Signal": "A_Formation",
        "CandleATime": str(bull_anchor.get('date', ''))
    }

def find_anchor_ll_sweep(df):
    """
    A = Low 2 (second lower low sweep).
    Rules:
      1. Need > 2 candles (at least 3 candles gap) between Low 1 and Low 2.
      2. In-between candles must NOT close below Low 1 (wicks allowed).
      3. Low 2 sweeps below Low 1.
    """
    if len(df) < 8:
        return None

    search_range = df.iloc[:-2]
    if search_range.empty or len(search_range) < 4:
        return None

    low_1_idx = search_range['low'].idxmin()
    low_1 = float(df.loc[low_1_idx, 'low'])

    sweep_candle, bounce_candle = df.iloc[-2], df.iloc[-1]
    sweep_idx = sweep_candle.name

    pos_low_1 = df.index.get_loc(low_1_idx)
    pos_sweep = df.index.get_loc(sweep_idx)
    if (pos_sweep - pos_low_1 - 1) < 2:
        return None

    inbetween_df = df.iloc[pos_low_1 + 1 : pos_sweep]
    if not inbetween_df.empty:
        if (inbetween_df['close'] < low_1).any():
            return None

    # Calculate ATR for intermediate swing bounce check (Datta Swing criteria: visible rally between L1 and L2)
    high_low_diff = (df['high'] - df['low']).abs()
    atr = float(high_low_diff.iloc[max(0, pos_sweep - 14) : pos_sweep].mean()) if len(df) >= 14 else (low_1 * 0.02)
    if atr <= 0:
        atr = low_1 * 0.02

    # Intermediate Swing Requirement: In-between candles must show a distinct swing bounce (>= 0.8x ATR or >= 1.5%)
    inbetween_high = float(inbetween_df['high'].max()) if not inbetween_df.empty else low_1
    min_bounce_req = low_1 + max(0.8 * atr, low_1 * 0.015)
    if inbetween_high < min_bounce_req:
        return None

    sweep_low = float(sweep_candle['low'])
    is_red = float(sweep_candle['close']) < float(sweep_candle['open'])
    is_green = float(sweep_candle['close']) >= float(sweep_candle['open'])

    # Var 1: Red sweep candle (dips/closes below Low 1, recovered by bounce candle)
    v1 = is_red and (sweep_low < low_1) and (float(sweep_candle['close']) > low_1)
    v2 = is_red and (float(sweep_candle['close']) < low_1) and (float(bounce_candle['close']) > low_1)
    
    # Var 2 (Page 10): Green/Neutral wick sweep candle (wick pierces Low 1, body closes green above Low 1)
    v3 = is_green and (sweep_low < low_1) and (float(sweep_candle['close']) > low_1)

    if not (v1 or v2 or v3):
        return None
    if not (float(bounce_candle['close']) > float(sweep_candle['high'])):
        return None

    pattern_name = "BULL_A_LL_Sweep_Var1" if (v1 or v2) else "BULL_A_LL_Sweep_Var2"

    anchor_close = float(bounce_candle['close'])
    anchor_high = max(float(sweep_candle['high']), float(bounce_candle['high']))
    sl_val = calculate_sl_buffer(sweep_low, side="BULL")
    return {
        "Pattern": pattern_name,
        "Close": anchor_close,
        "SL": sl_val,
        "AnchorHigh": anchor_high,
        "AnchorLow": sweep_low,
        "Signal": "Low2_Formation",
        "CandleATime": str(sweep_candle.get('date', ''))
    }

def find_anchor_hammer_baby(df):
    """A = baby/hammer/dragonfly candle inside/at bearish mother base with strong lower wick rejection."""
    if len(df) < 2:
        return None
    mother_candle, baby_candle = df.iloc[-2], df.iloc[-1]
    if not (float(mother_candle['close']) < float(mother_candle['open'])):
        return None
    is_green = float(baby_candle['close']) >= float(baby_candle['open'])
    b_open = float(baby_candle['open'])
    b_close = float(baby_candle['close'])
    b_high = float(baby_candle['high'])
    b_low = float(baby_candle['low'])

    total_range = b_high - b_low
    if total_range <= 0:
        return None

    body = abs(b_close - b_open)
    lower_wick = min(b_open, b_close) - b_low
    upper_wick = b_high - max(b_open, b_close)

    # 1. Lower wick must be dominant relative to body (at least 1.2x for green, 1.8x for red)
    min_wick_ratio = 1.2 if is_green else 1.8
    if lower_wick < (body * min_wick_ratio):
        return None
    if lower_wick <= upper_wick:
        return None

    # 2. Upper wick cap: Upper wick must not exceed 35% of total candle range or 50% of lower wick (filters spinning tops)
    if upper_wick > (total_range * 0.35) or upper_wick > (lower_wick * 0.50):
        return None

    # 3. Close conviction: Close must finish in upper 40% of the total candle span (>= 0.60 from low)
    close_position = (b_close - b_low) / total_range
    if close_position < 0.60:
        return None

    # 4. Containment / Location: Hammer must test the lower base/support of the bearish mother candle
    m_close = float(mother_candle['close'])
    if b_low > (m_close * 1.005):
        return None

    anchor_close = b_close
    sl_val = calculate_sl_buffer(b_low, side="BULL")
    return {
        "Pattern": "BULL_A_Baby_Candle",
        "Close": anchor_close,
        "SL": sl_val,
        "AnchorHigh": b_high,
        "AnchorLow": b_low,
        "Signal": "Baby_Formation",
        "CandleATime": str(baby_candle.get('date', ''))
    }

def find_anchor_bullish_harami(df):
    """A = bullish inside bar (cin) fully inside bearish mother body."""
    if len(df) < 2:
        return None
    bearish_mother, bullish_inside = df.iloc[-2], df.iloc[-1]
    m_open, m_close = float(bearish_mother['open']), float(bearish_mother['close'])
    i_open, i_close = float(bullish_inside['open']), float(bullish_inside['close'])
    if not (m_close < m_open and i_close > i_open):
        return None
    if not (float(bullish_inside['high']) <= m_open and float(bullish_inside['low']) >= m_close):
        return None
    # Body size ratio check: Inside body must be <= 65% of mother body (Datta rulebook)
    mother_body = m_open - m_close
    inside_body = i_close - i_open
    if mother_body > 0 and (inside_body / mother_body) > 0.65:
        return None
    inside_high = float(bullish_inside['high'])
    inside_low = float(bullish_inside['low'])
    anchor_close = i_close
    sl_val = calculate_sl_buffer(inside_low, side="BULL")
    return {
        "Pattern": "BULL_A_Harami",
        "Close": anchor_close,
        "SL": sl_val,
        "AnchorHigh": inside_high,
        "AnchorLow": inside_low,
        "Signal": "Harami_Formation",
        "CandleATime": str(bullish_inside.get('date', ''))
    }

def find_anchor_two_higher_highs(df):
    """Setup 3: A1 & A2 are two successive higher high candles with bullish engulfing structure."""
    if len(df) < 2:
        return None
    a1, a2 = df.iloc[-2], df.iloc[-1]
    if not (float(a1['close']) > float(a1['open']) and float(a2['close']) > float(a2['open'])):
        return None
    if not (float(a2['high']) > float(a1['high']) and float(a2['low']) > float(a1['low'])):
        return None
    a_high = max(float(a1['high']), float(a2['high']))
    a_low = min(float(a1['low']), float(a2['low']))
    anchor_close = float(a2['close'])
    sl_val = calculate_sl_buffer(a_low, side="BULL")
    return {
        "Pattern": "BULL_A_Two_Higher_Highs",
        "Close": anchor_close,
        "SL": sl_val,
        "AnchorHigh": a_high,
        "AnchorLow": a_low,
        "Signal": "HigherHigh_Engulf",
        "CandleATime": str(a2.get('date', ''))
    }

# ──────────────────────────────────────────────
#  ANCHOR BCD BREAKOUT SCANNER (A -> B -> C -> D)
# ──────────────────────────────────────────────

def scan_anchor_bcd_breakout(df_entry, df_anchor, anchor_tf="", entry_tf="", enable_swing_filter=None, swing_min_waves=3, swing_min_r2=0.55):
    """
    Two-phase A-first scanner with Institutional Phase 0 Parabolic Multi-Swing Filter:
      Phase 0: Multi-Swing Parabolic decay fitting (>= 3 waves, R^2 >= 0.55) & Terminal Base on df_anchor.
      Phase 1: Find anchor candle A (at or after the terminal base low).
      Phase 2: From A, scan forward sequentially: B (breakout > A.high) ->
               C (red retest) -> D (confirmation close > A.high).
      Returns first complete A -> B -> C -> D pattern, or None.
    """
    if df_entry is None or df_entry.empty or df_anchor is None or df_anchor.empty:
        return None

    tf_str = entry_tf or anchor_tf or "15minute"
    tf_minutes = get_tf_minutes(tf_str)
    if tf_minutes <= 0:
        tf_minutes = 15
    max_bc_candles = max(25, int(180 / tf_minutes))

    swing_meta = {"swing_waves": 0, "terminal_base": False, "terminal_date": ""}
    if enable_swing_filter is None:
        try:
            import json, paths, os
            if os.path.exists(paths.PROGRAM_CONFIG_FILE):
                with open(paths.PROGRAM_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg_all = json.load(f)
                enable_swing_filter = bool(cfg_all.get("daily", {}).get("enable_swing_filter", True))
                swing_min_waves = int(cfg_all.get("daily", {}).get("swing_min_waves", swing_min_waves))
                swing_min_r2 = float(cfg_all.get("daily", {}).get("swing_min_r2", swing_min_r2))
        except Exception:
            enable_swing_filter = False

    if enable_swing_filter:
        sw_res = detect_parabolic_multi_swings(df_anchor, side="BULL", min_swings=swing_min_waves, min_r2=swing_min_r2, max_bars_after_terminal=45, timeframe_str=anchor_tf)
        swing_meta = {
            "swing_waves": sw_res.get("valid_arch_count", 0),
            "terminal_base": sw_res.get("has_terminal_base", False),
            "terminal_date": sw_res.get("terminal_swing_date", ""),
            "terminal_idx": sw_res.get("terminal_swing_idx"),
            "tier": sw_res.get("tier", 2),
            "tier_label": sw_res.get("tier_label", "TIER_2_CORE"),
            "tier_badge": sw_res.get("tier_badge", "🥈 T2")
        }

    anchor_funcs = [
        find_anchor_bullish_engulfing,
        find_anchor_ll_sweep,
        find_anchor_hammer_baby,
        find_anchor_bullish_harami,
        find_anchor_two_higher_highs
    ]

    # ── Phase 1: Find anchor A candles ──
    anchors = []
    for a_idx in range(1, len(df_entry) - 2):
        a = df_entry.iloc[a_idx]
        sub_df_direct = df_entry.iloc[: a_idx + 1]

        anchor_match = None
        for fn in anchor_funcs:
            res = fn(sub_df_direct)
            if res:
                anchor_match = res
                break

        benchmark = float(anchor_match.get("AnchorHigh", a['high'])) if anchor_match else float(a['high'])
        a_low = float(anchor_match.get("AnchorLow", a['low'])) if anchor_match else float(a['low'])
        invalidation = anchor_match["SL"] if anchor_match and "SL" in anchor_match else calculate_sl_buffer(a_low, side="BULL")
        anchor_name = anchor_match["Pattern"] if anchor_match else "BULL_A_Base"

        # Left-Side Rule: no close below A.low in preceding 100 candles
        left_df = df_entry.iloc[max(0, a_idx - 100) : a_idx]
        if not left_df.empty and float(left_df['close'].min()) < a_low:
            continue

        # Pre-compute targets for NoPA filter
        t1, t2, t3 = find_profit_targets(df_anchor, benchmark, stop_loss=invalidation)

        # NoPA: discard if SL/T1/T2 already closed past post-A (closing basis)
        if t1 is not None:
            after_a = df_entry.iloc[a_idx + 1 :]
            if not after_a.empty:
                if float(after_a['close'].min()) < a_low:
                    continue
                if float(after_a['close'].max()) >= t1:
                    continue
                if t2 is not None and float(after_a['close'].max()) >= t2:
                    continue

        a_time_val = anchor_match.get("CandleATime") if anchor_match and anchor_match.get("CandleATime") else str(a.get('date', ''))
        
        # Sequence gatekeeper: Allow Anchor A to form within the terminal base window (allowing 5-bar lookback for base confirmation)
        if swing_meta.get("terminal_base") and swing_meta.get("terminal_date") and a_time_val:
            term_idx = swing_meta.get("terminal_idx")
            if term_idx is not None:
                if a_idx < max(0, term_idx - 5):
                    continue
            else:
                try:
                    a_dt = pd.to_datetime(clean_timestamp(a_time_val))
                    t_dt = pd.to_datetime(clean_timestamp(swing_meta["terminal_date"]))
                    if (t_dt - a_dt).days > 8:
                        continue
                except Exception:
                    pass

        anchors.append({
            "idx": a_idx, "a": a, "benchmark": benchmark,
            "invalidation": invalidation, "anchor_name": anchor_name, "a_low": a_low,
            "t1": t1, "t2": t2, "t3": t3, "a_time": a_time_val
        })

    valid_matches = []
    # ── Phase 2: For each anchor, scan forward B -> C -> D ──
    for cand in reversed(anchors):
        a_idx = cand["idx"]
        a = cand["a"]
        benchmark = cand["benchmark"]
        invalidation = cand["invalidation"]
        anchor_name = cand["anchor_name"]
        a_low = cand["a_low"]
        t1 = cand.get("t1")

        remaining = df_entry.iloc[a_idx + 1:]
        if len(remaining) < 3:
            continue

        # Point B: FIRST candle after A closing above benchmark (max 60 candles, invalid if close < a_low)
        b_idx = None
        for j in range(min(60, len(remaining))):
            c_close_b = float(remaining.iloc[j]['close'])
            if c_close_b < a_low:
                break
            if c_close_b > benchmark:
                b_idx = a_idx + 1 + j
                break
        if b_idx is None:
            continue

        # Point C: FIRST candle AFTER B with red retest (dips to/close to benchmark, stays above A.low)
        c_slice = df_entry.iloc[b_idx + 1:]
        c_idx = None
        risk_dist = max(0.50, benchmark - a_low)
        max_b_excursion = benchmark + (1.5 * risk_dist)
        if t1 is not None and t1 > benchmark:
            max_b_excursion = min(max_b_excursion, float(t1))

        for j in range(len(c_slice)):
            # Spacing guard: Retest C must form within max_bc_candles of breakout B
            if j > max_bc_candles:
                break
            c_row = c_slice.iloc[j]
            # Excursion guard: If price already rallied > 1.5x risk or reached T1, move is exhausted
            if float(c_row['high']) > max_b_excursion:
                break
            c_low = float(c_row['low'])
            c_close = float(c_row['close'])
            c_open = float(c_row['open'])
            is_red = c_close < c_open
            if (c_low <= benchmark and c_close >= a_low and is_red) or \
               (c_low <= a_low and c_close >= a_low and c_close < float(a['open']) and is_red):
                c_idx = b_idx + 1 + j
                break
        if c_idx is None:
            continue

        # Point D: FIRST candle AFTER C closing above benchmark (color independent)
        d_slice = df_entry.iloc[c_idx + 1:]
        d_idx = None
        is_near_close_d = False
        max_cd_candles = 60
        for j in range(min(max_cd_candles, len(d_slice))):
            curr_idx = c_idx + 1 + j
            d_row = d_slice.iloc[j]
            d_close = float(d_row['close'])
            d_open = float(d_row['open'])

            if d_close < a_low:
                break

            # Case A: Completed Historical Candle (100% closed)
            if curr_idx < len(df_entry) - 1:
                if d_close > benchmark:
                    d_idx = curr_idx
                    break

            # Case B: Current Live Active Forming Candle (near-close >= 80% with dual guards)
            else:
                tf_to_check = entry_tf or anchor_tf
                if tf_to_check and is_live_candle_near_close(d_row.get('date'), tf_to_check, completion_pct=0.80):
                    # Guard 1: Benchmark Buffer Guard (+0.3%)
                    if d_close >= (benchmark * 1.003):
                        # Guard 2: Proportional Volume Validation Guard (60% of 20-period avg volume at 80% time)
                        vol_passed = True
                        if 'volume' in df_entry.columns and curr_idx >= 20:
                            avg_vol_20 = float(df_entry['volume'].iloc[curr_idx - 20 : curr_idx].mean())
                            curr_vol = float(d_row.get('volume', 0))
                            if avg_vol_20 > 0 and curr_vol < (0.60 * avg_vol_20):
                                vol_passed = False
                        if vol_passed:
                            d_idx = curr_idx
                            is_near_close_d = True
                            break

        if d_idx is None:
            continue

        d = df_entry.iloc[d_idx]

        # Invalidation between A and D: Option A - no candle closes below A.low (A.low floor line)
        between = df_entry.iloc[a_idx + 1 : d_idx]
        if not between.empty and float(between['close'].min()) < a_low:
            continue

        close_price = float(d['close'])
        sl_val = invalidation
        t1, t2, t3 = find_profit_targets(df_anchor, close_price, stop_loss=sl_val)
        if t1 is None or close_price >= t1:
            continue

        stage_status = "EARLY_D_ENTRY" if is_near_close_d else "FRESH_ENTRY"
        priority_level = "HIGH_PRIORITY"

        # Post-D 3-Tier Classification & Setup Freshness Filter
        after_d = df_entry.iloc[d_idx + 1 :]
        candles_since_d = len(df_entry) - 1 - d_idx
        latest_close = float(df_entry.iloc[-1]['close'])

        # Rule 1: Discard stale setups older than 60 candles to wait for new setup in next cycle
        if candles_since_d > 60:
            continue

        # Rule 2: Discard if current price closed below SL floor line
        if latest_close <= invalidation:
            continue

        if not after_d.empty:
            # 3. Discard if SL hit in any candle after D (A.low - buffer)
            if float(after_d['close'].min()) <= invalidation:
                continue
            # 4. Check if T1 (or 80% T1) has been reached after D
            t1_80 = close_price + 0.80 * (t1 - close_price)
            if float(after_d['high'].max()) >= t1_80 or float(after_d['close'].max()) >= t1:
                t2_gap_pct = ((t2 - t1) / t1) if (t2 is not None and t1 > 0) else 0.0
                # If T3 reached, T2 reached, no T2 available, or T2 has less gap (< 10%) -> Discard scan
                if (t3 is not None and float(after_d['close'].max()) >= t3) or t2 is None or t2_gap_pct < 0.10 or float(after_d['close'].max()) >= t2:
                    continue
                # T1 was hit with sufficient T2 room -> Qualifies as LOW PRIORITY T2 Continuation if intact
                stage_status = "T2_CONTINUATION"
                priority_level = "LOW_PRIORITY"
                sl_val = t1  # Trailed SL to T1 level to protect banked gains
            else:
                # 5. Post-D Retest: Price is hovering near Benchmark (+/- 2.5%) without hitting T1 or SL
                if benchmark > 0 and (benchmark * 0.980 <= latest_close <= benchmark * 1.025):
                    stage_status = "POST_D_RETEST"
                    close_price = latest_close

        risk = close_price - sl_val
        if risk <= 0 or risk < close_price * 0.002 or ((t1 - close_price) / risk) < 1.5:
            continue

        rr = (t1 - close_price) / risk if risk > 0 else 0
        short_names = {
            "BULL_A_ABCD_Engulf": "BE_ABCD",
            "BULL_A_LL_Sweep": "LL_ABCD",
            "BULL_A_LL_Sweep_Var1": "LL_ABCD",
            "BULL_A_LL_Sweep_Var2": "LL_ABCD",
            "BULL_A_Baby_Candle": "HAMMER_ABCD",
            "BULL_A_Harami": "HARAMI_ABCD",
            "BULL_A_Two_Higher_Highs": "HH_ABCD",
            "BULL_A_Base": "BASE_ABCD"
        }
        pattern_label = short_names.get(anchor_name, "BASE_ABCD")
        if is_near_close_d:
            pattern_label += "_EARLY"
        d_time_str = str(d.get("date", ""))
        a_time_str = str(cand.get("a_time") or a.get("date", ""))

        # ── Volume Profile Analysis on B-C-D (Option Chart Intraday RVOL) ──
        vol_b_ratio = 1.0
        vol_c_ratio = 1.0
        vol_d_ratio = 1.0
        vol_confirmed = True
        vol_profile_score = 3
        opt_rvol_badge = "NORMAL"
        if 'volume' in df_entry.columns and d_idx >= 5:
            try:
                avg_vol_20 = float(df_entry['volume'].iloc[max(0, d_idx - 20):d_idx].mean())
                if avg_vol_20 > 0:
                    vb = float(df_entry['volume'].iloc[b_idx])
                    vc = float(df_entry['volume'].iloc[c_idx])
                    vd = float(df_entry['volume'].iloc[d_idx])
                    vol_b_ratio = round(vb / avg_vol_20, 2)
                    vol_c_ratio = round(vc / vb, 2) if vb > 0 else round(vc / avg_vol_20, 2)
                    vol_d_ratio = round(vd / avg_vol_20, 2)
                    c_rvol = round(vc / avg_vol_20, 2)

                    # Retest Volume Dry-up: VC should ideally be lower than VB (pullback on declining volume <= 0.85)
                    # Trigger Volume Expansion: VD should be expanding relative to 20-period avg (>= 1.5x)
                    is_c_dryup = (vol_c_ratio <= 0.85) or (c_rvol <= 0.85) or (vc <= avg_vol_20)
                    is_d_expansion = (vol_d_ratio >= 1.50) or (is_near_close_d and vol_d_ratio >= 1.00) or (vol_d_ratio >= 1.20)
                    vol_confirmed = bool(is_c_dryup and is_d_expansion)

                    if vol_d_ratio >= 2.0:
                        opt_rvol_badge = f"⚡ OPT RVOL {vol_d_ratio:.1f}x"
                    elif vol_d_ratio >= 1.5:
                        opt_rvol_badge = f"📈 OPT RVOL {vol_d_ratio:.1f}x"
                    elif is_c_dryup and vol_d_ratio >= 1.2:
                        opt_rvol_badge = f"🎯 DRYUP+EXP ({vol_d_ratio:.1f}x)"

                    if vol_confirmed and vol_d_ratio >= 1.5:
                        vol_profile_score = 5
                    elif vol_confirmed and vol_d_ratio >= 1.2:
                        vol_profile_score = 4
                    elif is_c_dryup or is_d_expansion:
                        vol_profile_score = 3
                    else:
                        vol_profile_score = 2
            except Exception:
                pass

        twap_c_info = calculate_twap_c_stability(df_entry.iloc[c_idx:d_idx + 1], risk_dist=max(0.50, benchmark - a_low))

        valid_matches.append({
            "Pattern": pattern_label,
            "SL": sl_val,
            "T1": t1,
            "T2": t2,
            "T3": t3,
            "Close": close_price,
            "RR": round(rr, 2),
            "CandleTime": d_time_str,
            "CandleATime": a_time_str,
            "Benchmark": benchmark,
            "AnchorFloor": a_low,
            "Direction": "BULL",
            "Stage_Status": stage_status,
            "Priority": priority_level,
            "d_idx": d_idx,
            "vol_b_ratio": vol_b_ratio,
            "vol_c_ratio": vol_c_ratio,
            "vol_d_ratio": vol_d_ratio,
            "opt_rvol_badge": opt_rvol_badge,
            "vol_confirmed": vol_confirmed,
            "vol_score": vol_profile_score,
            "twap_c_stable": twap_c_info.get("twap_stable", False),
            "twap_c_score": twap_c_info.get("twap_score", 0.0),
            "twap_c_std": twap_c_info.get("twap_std", 0.0)
        })

    if not valid_matches:
        return None

    PATTERN_PRIORITY_MAP = {
        "BE_ABCD": 5,
        "LL_ABCD": 5,
        "HAMMER_ABCD": 4,
        "HARAMI_ABCD": 4,
        "HH_ABCD": 3,
        "BASE_ABCD": 1
    }

    def _pattern_rank(match_obj):
        p_name = match_obj.get("Pattern", "").replace("_EARLY", "")
        return PATTERN_PRIORITY_MAP.get(p_name, 2)

    # Prefer Primary Reversal over Continuation Base, then LATEST formed pattern (d_idx), then HIGH_PRIORITY, then R:R
    valid_matches.sort(key=lambda x: (_pattern_rank(x), x["d_idx"], x["Priority"] == "HIGH_PRIORITY", x["RR"]), reverse=True)
    best_latest = valid_matches[0]
    best_latest.pop("d_idx", None)

    sw_waves = swing_meta.get("swing_waves", 0)
    term_base = swing_meta.get("terminal_base", False)
    p_rank = _pattern_rank(best_latest)
    rr_val = float(best_latest.get("RR", 0.0))
    p_name = str(best_latest.get("Pattern", ""))
    # True 5-Anchor Reversal Classifiers: Engulfing, LL Sweep, Hammer Baby, Harami, Two Higher Highs
    is_true_anchor = any(k in p_name for k in ["BE_ABCD", "LL_ABCD", "HAMMER_ABCD", "HARAMI_ABCD", "HH_ABCD"]) and "BASE_ABCD" not in p_name
    is_higher_timeframe = str(anchor_tf).lower() in ["day", "week", "1d", "1w", "daily", "weekly", "d", "w"]
    twap_c_stable = bool(best_latest.get("twap_c_stable", False))
    opt_vol_score = int(best_latest.get("vol_score", 3))

    # Option A Balanced Tiering (T1 Gold 1:2 / 2.0, T2 Core 1:1.5 / 1.5):
    # Tier 1 (Gold): 
    #   - Intraday Options: Strictly 5 True Anchors + (>=3 Waves or Tier 1 Multi-Swing Arch or Stable TWAP C Base or Option RVOL Surge >= 1.5x) + R:R >= 2.0
    #   - Daily/Weekly Equities: True Anchor / Institutional Liquidity Base + R:R >= 2.0
    # Tier 2 (Core): 5 True Anchors (>=2 Waves / R:R >= 1.5) OR strong BASE_ABCD with (>=3 Waves and R:R >= 2.0) OR Higher TF with R:R >= 1.5 OR TWAP C Stable (R:R >= 1.5)
    # Tier 3 (Momentum): Standard/early BASE_ABCD and trend continuations (R:R >= 1.5)
    if rr_val >= 2.0 and (
        (is_true_anchor and (sw_waves >= 2 or is_higher_timeframe or swing_meta.get("tier") == 1 or (twap_c_stable and sw_waves >= 1) or opt_vol_score >= 5))
        or (is_higher_timeframe and (is_true_anchor or term_base))
        or (not is_true_anchor and sw_waves >= 3 and term_base)
    ):
        tier = 1
        tier_label = "TIER_1_GOLD"
        tier_badge = "🥇 T1"
    elif (is_true_anchor and (sw_waves >= 2 or p_rank >= 3 or rr_val >= 1.5)) or ((sw_waves >= 3 or swing_meta.get("tier") == 1) and rr_val >= 2.0) or (is_higher_timeframe and rr_val >= 1.5) or (twap_c_stable and rr_val >= 1.5):
        tier = 2
        tier_label = "TIER_2_CORE"
        tier_badge = "🥈 T2"
    else:
        tier = 3
        tier_label = "TIER_3_MOMENTUM"
        tier_badge = "🥉 T3"

    best_latest["tier"] = tier
    best_latest["tier_label"] = tier_label
    best_latest["tier_badge"] = tier_badge
    best_latest["swing_waves"] = sw_waves
    best_latest["terminal_base"] = term_base
    best_latest["twap_c_stable"] = twap_c_stable
    best_latest["twap_c_score"] = best_latest.get("twap_c_score", 0.0)
    best_latest["twap_c_std"] = best_latest.get("twap_c_std", 0.0)
    try:
        from swing_detection import calculate_vcp_metrics
    except ImportError:
        from common.swing_detection import calculate_vcp_metrics
    vcp_m = calculate_vcp_metrics(df_entry)
    best_latest["atr_ratio"] = vcp_m.get("atr_ratio", 1.0)
    best_latest["is_squeeze"] = vcp_m.get("is_squeeze", False)
    best_latest["vcp_tier"] = vcp_m.get("vcp_tier", "NORMAL")
    best_latest["vcp_badge"] = vcp_m.get("vcp_badge", "")
    best_latest["opt_rvol_badge"] = best_latest.get("opt_rvol_badge", "NORMAL")
    return best_latest


def scan_pattern_lifecycle_stage(df_entry, df_anchor, anchor_tf="", entry_tf="", enable_swing_filter=None, swing_min_waves=3, swing_min_r2=0.55, is_option=False):
    """
    Evaluates the current maturity of a symbol across the 4-stage lifecycle funnel:
      1. STAGE_FULL_ABCD: D breakout confirmed or near-close triggered (Ready for immediate execution).
      2. STAGE_A_PLUS_READY: Phase 0 Parabolic (>= 3 waves, R^2 >= 0.55, Terminal Base) + A + B + C formed. Coiled at D trigger.
      3. STAGE_A_READY: Valid Anchor A + Pullback B + Retest C formed. Waiting for D trigger.
      4. STAGE_B_ANCHOR: Valid Anchor A formed (Engulfing, Sweep, Hammer, Harami, Two HH, Base). B/C still developing.
    Returns: dict with stage details, or None.
    """
    if df_entry is None or df_entry.empty or df_anchor is None or df_anchor.empty:
        return None

    # Step 1: Check if Full ABCD setup has already triggered
    full_setup = scan_anchor_bcd_breakout(
        df_entry, df_anchor, anchor_tf=anchor_tf, entry_tf=entry_tf,
        enable_swing_filter=enable_swing_filter, swing_min_waves=swing_min_waves, swing_min_r2=swing_min_r2
    )
    if full_setup:
        return {
            "stage": "STAGE_FULL_ABCD",
            "setup": full_setup,
            "pattern": full_setup.get("Pattern"),
            "benchmark": full_setup.get("Benchmark"),
            "sl": full_setup.get("SL"),
            "close": full_setup.get("Close"),
            "t1": full_setup.get("T1"),
            "t2": full_setup.get("T2"),
            "t3": full_setup.get("T3"),
            "rr": full_setup.get("RR"),
            "tier": full_setup.get("tier", 2),
            "tier_label": full_setup.get("tier_label", "TIER_2_CORE"),
            "tier_badge": full_setup.get("tier_badge", "🥈 T2"),
            "candle_a_time": full_setup.get("CandleATime"),
            "candle_d_time": full_setup.get("CandleTime"),
            "anchor_floor": full_setup.get("AnchorFloor"),
            "atr_ratio": full_setup.get("atr_ratio", 1.0),
            "is_squeeze": full_setup.get("is_squeeze", False),
            "vcp_tier": full_setup.get("vcp_tier", "NORMAL"),
            "vcp_badge": full_setup.get("vcp_badge", ""),
            "twap_c_stable": full_setup.get("twap_c_stable", False),
            "twap_c_score": full_setup.get("twap_c_score", 0.0),
            "twap_c_std": full_setup.get("twap_c_std", 0.0)
        }

    # Step 2: Evaluate Institutional Parabolic Multi-Swing context on Anchor TF
    swing_meta = {"swing_waves": 0, "terminal_base": False, "terminal_date": ""}
    if enable_swing_filter is None:
        try:
            import json, paths, os
            if os.path.exists(paths.PROGRAM_CONFIG_FILE):
                with open(paths.PROGRAM_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg_all = json.load(f)
                enable_swing_filter = bool(cfg_all.get("daily", {}).get("enable_swing_filter", True))
                swing_min_waves = int(cfg_all.get("daily", {}).get("swing_min_waves", swing_min_waves))
                swing_min_r2 = float(cfg_all.get("daily", {}).get("swing_min_r2", swing_min_r2))
        except Exception:
            enable_swing_filter = False

    if enable_swing_filter:
        sw_res = detect_parabolic_multi_swings(df_anchor, side="BULL", min_swings=swing_min_waves, min_r2=swing_min_r2, max_bars_after_terminal=45, timeframe_str=anchor_tf)
        swing_meta = {
            "swing_waves": sw_res.get("valid_arch_count", 0),
            "terminal_base": sw_res.get("has_terminal_base", False),
            "terminal_date": sw_res.get("terminal_swing_date", ""),
            "terminal_idx": sw_res.get("terminal_swing_idx"),
            "tier": sw_res.get("tier", 2),
            "tier_label": sw_res.get("tier_label", "TIER_2_CORE"),
            "tier_badge": sw_res.get("tier_badge", "🥈 T2")
        }

    try:
        from swing_detection import calculate_vcp_metrics
    except ImportError:
        from common.swing_detection import calculate_vcp_metrics
    vcp_metrics = calculate_vcp_metrics(df_entry)

    anchor_funcs = [
        find_anchor_bullish_engulfing,
        find_anchor_ll_sweep,
        find_anchor_hammer_baby,
        find_anchor_bullish_harami,
        find_anchor_two_higher_highs
    ]

    short_names = {
        "BULL_A_ABCD_Engulf": "BE_ABCD",
        "BULL_A_LL_Sweep": "LL_ABCD",
        "BULL_A_LL_Sweep_Var1": "LL_ABCD",
        "BULL_A_LL_Sweep_Var2": "LL_ABCD",
        "BULL_A_Baby_Candle": "HAMMER_ABCD",
        "BULL_A_Harami": "HARAMI_ABCD",
        "BULL_A_Two_Higher_Highs": "HH_ABCD",
        "BULL_A_Base": "BASE_ABCD"
    }

    df_target = df_anchor if (df_anchor is not None and len(df_anchor) >= 8) else df_entry
    latest_close = float(df_entry.iloc[-1]['close']) if (df_entry is not None and not df_entry.empty) else float(df_target.iloc[-1]['close'])
    opt_mode = is_option or ("minute" in str(anchor_tf).lower() and len(df_target) <= 180)
    tf_str = anchor_tf or entry_tf or "15minute"
    tf_minutes = get_tf_minutes(tf_str)
    if tf_minutes <= 0:
        tf_minutes = 15
    max_bc_candles = max(25, int(180 / tf_minutes))

    # Search backward from newest candles on Anchor TF for the most recent valid active Anchor A
    for a_idx in range(len(df_target) - 2, max(0, len(df_target) - 75), -1):
        a = df_target.iloc[a_idx]
        sub_df_direct = df_target.iloc[: a_idx + 1]

        anchor_match = None
        for fn in anchor_funcs:
            res = fn(sub_df_direct)
            if res:
                anchor_match = res
                break

        if not anchor_match:
            continue

        benchmark = float(anchor_match.get("AnchorHigh", a['high']))
        a_low = float(anchor_match.get("AnchorLow", a['low']))
        invalidation = anchor_match["SL"] if "SL" in anchor_match else calculate_sl_buffer(a_low, side="BULL")
        anchor_name = anchor_match["Pattern"]
        pattern_label = short_names.get(anchor_name, "BASE_ABCD")
        a_time_val = str(anchor_match.get("CandleATime") or a.get("date", ""))

        # 1. Left-Side Rule on Anchor TF:
        # On Spot equity charts, check 100 candles. On Option charts (with weekly/monthly lifespans and moneyness decay),
        # scope lookback to 30 bars (~2-3 days) to prevent historical out-of-the-money penny prices from falsely invalidating live option bases.
        lookback_bars = 30 if opt_mode else 100
        left_df = df_target.iloc[max(0, a_idx - lookback_bars) : a_idx]
        if not left_df.empty and float(left_df['close'].min()) < a_low:
            continue

        t1, t2, t3 = find_profit_targets(df_anchor, benchmark, stop_loss=invalidation)
        risk = benchmark - invalidation
        rr = (t1 - benchmark) / risk if (t1 and risk > 0) else 0.0

        # 2. Hard Anchor TF Eviction Rule: Discard if post-A closed <= SL or >= T1
        after_a = df_target.iloc[a_idx + 1:]
        if not after_a.empty:
            if float(after_a['close'].min()) <= invalidation:
                continue
            if t1 is not None and float(after_a['close'].max()) >= t1:
                continue
            if t2 is not None and float(after_a['close'].max()) >= t2:
                continue
        if latest_close <= invalidation:
            continue
        if t1 is not None and latest_close >= t1:
            continue

        # 3. Check Point B on Anchor TF
        b_idx = None
        for j in range(len(after_a)):
            if float(after_a.iloc[j]['close']) > benchmark:
                b_idx = a_idx + 1 + j
                break

        if b_idx is not None:
            # 4. Check Point C on Anchor TF
            c_slice = df_target.iloc[b_idx + 1:]
            c_idx = None
            risk_dist = max(0.50, benchmark - a_low)
            max_b_excursion = benchmark + (1.5 * risk_dist)
            if t1 is not None and t1 > benchmark:
                max_b_excursion = min(max_b_excursion, float(t1))

            for j in range(len(c_slice)):
                if j > max_bc_candles:
                    break
                c_row = c_slice.iloc[j]
                if float(c_row['high']) > max_b_excursion:
                    break
                c_low = float(c_row['low'])
                c_close = float(c_row['close'])
                c_open = float(c_row['open'])
                c_high = float(c_row['high'])
                is_red = c_close <= c_open
                is_doji_or_narrow = (abs(c_close - c_open) / max(0.05, c_high - c_low)) <= 0.40

                # Confirmed Retest: Dips to or near benchmark (+/- 1.5%), holds above A.low, and is either a red pullback or a narrow absorption bar
                if (c_low <= benchmark * 1.015 and c_close >= a_low and (is_red or is_doji_or_narrow)) or \
                   (c_low <= a_low and c_close >= a_low and c_close < float(a['open']) and is_red):
                    c_idx = b_idx + 1 + j
                    break

            if c_idx is not None:
                # Stage A / A+: Both B and C are formed on Anchor TF! Coiling for D breakout
                b_row = df_target.iloc[b_idx]
                c_row = df_target.iloc[c_idx]
                twap_c_info = calculate_twap_c_stability(df_target.iloc[c_idx:], risk_dist=risk_dist)
                twap_c_stable = bool(twap_c_info.get("twap_stable", False))
                has_parabolic = bool(
                    (swing_meta.get("swing_waves", 0) >= 2 and swing_meta.get("terminal_base", False))
                    or (swing_meta.get("swing_waves", 0) >= 1 and twap_c_stable and swing_meta.get("terminal_base", False))
                )
                stage_name = "STAGE_A_PLUS_READY" if has_parabolic else "STAGE_A_READY"
                tier_val = 1 if has_parabolic else 2
                tier_lbl = "TIER_1_GOLD" if has_parabolic else "TIER_2_CORE"
                tier_bdg = "🥇 T1" if has_parabolic else "🥈 T2"
                dist_pct = round(((benchmark - latest_close) / latest_close) * 100, 2) if latest_close > 0 else 0.0

                return {
                    "stage": stage_name,
                    "pattern": pattern_label,
                    "anchor_name": anchor_name,
                    "benchmark": benchmark,
                    "sl": invalidation,
                    "close": latest_close,
                    "c_low": float(c_row['low']),
                    "dist_to_trigger_pct": dist_pct,
                    "t1": t1, "t2": t2, "t3": t3,
                    "rr": round(rr, 2),
                    "tier": tier_val,
                    "tier_label": tier_lbl,
                    "tier_badge": tier_bdg,
                    "candle_a_time": a_time_val,
                    "candle_b_time": str(b_row.get("date", "")),
                    "candle_c_time": str(c_row.get("date", "")),
                    "anchor_floor": a_low,
                    "swing_waves": swing_meta.get("swing_waves", 0),
                    "terminal_base": swing_meta.get("terminal_base", False),
                    "atr_ratio": vcp_metrics.get("atr_ratio", 1.0),
                    "is_squeeze": vcp_metrics.get("is_squeeze", False),
                    "vcp_tier": vcp_metrics.get("vcp_tier", "NORMAL"),
                    "vcp_badge": vcp_metrics.get("vcp_badge", ""),
                    "twap_c_stable": twap_c_stable,
                    "twap_c_score": twap_c_info.get("twap_score", 0.0),
                    "twap_c_std": twap_c_info.get("twap_std", 0.0)
                }

        # Stage B: Valid Anchor A formed on Anchor TF with 100-candle rule, waiting for B / C
        dist_pct = round(((benchmark - latest_close) / latest_close) * 100, 2) if latest_close > 0 else 0.0
        return {
            "stage": "STAGE_B_ANCHOR",
            "pattern": pattern_label,
            "anchor_name": anchor_name,
            "benchmark": benchmark,
            "sl": invalidation,
            "close": latest_close,
            "dist_to_trigger_pct": dist_pct,
            "t1": t1, "t2": t2, "t3": t3,
            "rr": round(rr, 2),
            "tier": 3,
            "tier_label": "TIER_3_MOMENTUM",
            "tier_badge": "🌱 B",
            "candle_a_time": a_time_val,
            "anchor_floor": a_low,
            "swing_waves": swing_meta.get("swing_waves", 0),
            "terminal_base": swing_meta.get("terminal_base", False),
            "atr_ratio": vcp_metrics.get("atr_ratio", 1.0),
            "vcp_badge": vcp_metrics.get("vcp_badge", ""),
            "twap_c_stable": False,
            "twap_c_score": 0.0,
            "twap_c_std": 0.0
        }

    return None



# ──────────────────────────────────────────────
#  SHARED ENGINE UTILITIES (identical between engines)
# ──────────────────────────────────────────────



def scan_trend_continuation_reentry(df_entry, df_anchor):
    """
    Setup Page 16 (Bullish Trend Continuation + Re-Entry):
    1. Context: Established Uptrend (Higher Highs & Higher Lows in preceding window).
    2. Retest: Price pulls back to prior swing support level.
    3. Trigger: Bullish Engulfing or Reclaim candle forms at support.
    4. Execution: Immediate Re-entry on the next candle close (No BCD delay).
    """
    if len(df_entry) < 20:
        return None

    lookback = df_entry.iloc[-25:-2]
    if lookback.empty or len(lookback) < 10:
        return None

    mid_point = len(lookback) // 2
    part1 = lookback.iloc[:mid_point]
    part2 = lookback.iloc[mid_point:]

    if not (part2['high'].max() > part1['high'].max() and part2['low'].min() > part1['low'].min()):
        return None

    trigger_candle = df_entry.iloc[-2]
    current_candle = df_entry.iloc[-1]

    is_green_trigger = float(trigger_candle['close']) > float(trigger_candle['open'])
    if not is_green_trigger:
        return None

    support_level = float(part2['low'].min())
    trigger_low = float(trigger_candle['low'])
    trigger_close = float(trigger_candle['close'])

    if not (trigger_low <= (support_level * 1.015) and trigger_close >= support_level):
        return None

    entry_price = float(current_candle['close'])
    sl_val = round(trigger_low - max(0.50, trigger_low * 0.02), 2)

    if entry_price <= sl_val:
        return None

    t1, t2, t3 = find_profit_targets(df_anchor, entry_price, stop_loss=sl_val)
    if t1 is None or t1 <= entry_price:
        return None

    risk = entry_price - sl_val
    if risk <= 0 or risk < entry_price * 0.002 or ((t1 - entry_price) / risk) < 1.5:
        return None

    try:
        from swing_detection import calculate_vcp_metrics
    except ImportError:
        from common.swing_detection import calculate_vcp_metrics
    vcp_m = calculate_vcp_metrics(df_entry)

    rr = (t1 - entry_price) / risk
    return {
        "Pattern": "TREND_CONT_BULL",
        "SL": sl_val,
        "T1": t1,
        "T2": t2,
        "T3": t3,
        "Entry": entry_price,
        "Close": entry_price,
        "RR": round(rr, 2),
        "Signal": "Immediate_ReEntry",
        "CandleTime": str(current_candle.get("date", "")),
        "CandleATime": str(trigger_candle.get("date", "")),
        "D_time": str(current_candle.get("date", "")),
        "A_time": str(trigger_candle.get("date", "")),
        "tier": 3,
        "tier_label": "TIER_3_MOMENTUM",
        "tier_badge": "🥉 T3",
        "swing_waves": 1,
        "terminal_base": False,
        "direction": "BULL",
        "atr_ratio": vcp_m.get("atr_ratio", 1.0),
        "is_squeeze": vcp_m.get("is_squeeze", False),
        "vcp_tier": vcp_m.get("vcp_tier", "NORMAL"),
        "vcp_badge": vcp_m.get("vcp_badge", "")
    }
