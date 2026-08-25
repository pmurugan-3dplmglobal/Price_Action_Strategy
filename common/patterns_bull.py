"""
Bullish price action pattern detectors: 5 anchor patterns (engulfing, LL sweep,
hammer baby, harami, two higher highs), A-B-C-D breakout scanner, and trend
continuation re-entry (Page 16).
Extracted from trading_core.py (2026-08-11).
"""
import logging
import pandas as pd
from datetime import datetime as dt

from targets import (
    find_profit_targets, check_left_side_rule,
    calculate_sl_buffer, calculate_position_size, calc_rr
)
from timeframe_utils import get_adaptive_lookback, resample_timeframe, trading_days_between, is_live_candle_near_close
from swing_detection import (
    is_parabolic_arch_enhanced,
    extract_swing_pivots,
    validate_parabolic_cascade_structure,
    detect_parabolic_multi_swings
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
    if not (float(bearish_mother['close']) < float(bearish_mother['open']) and float(bullish_inside['close']) > float(bullish_inside['open'])):
        return None
    if not (float(bullish_inside['high']) <= float(bearish_mother['open']) and float(bullish_inside['low']) >= float(bearish_mother['close'])):
        return None
    inside_high = float(bullish_inside['high'])
    inside_low = float(bullish_inside['low'])
    anchor_close = float(bullish_inside['close'])
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
        sw_res = detect_parabolic_multi_swings(df_anchor, side="BULL", min_swings=swing_min_waves, min_r2=swing_min_r2, max_bars_after_terminal=45)
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
        a_low = float(a['low'])
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

        remaining = df_entry.iloc[a_idx + 1:]
        if len(remaining) < 3:
            continue

        # Point B: FIRST candle after A closing above benchmark
        b_idx = None
        for j in range(len(remaining)):
            if float(remaining.iloc[j]['close']) > benchmark:
                b_idx = a_idx + 1 + j
                break
        if b_idx is None:
            continue

        # Point C: FIRST candle AFTER B with red retest (dips to/close to benchmark, stays above A.low)
        c_slice = df_entry.iloc[b_idx + 1:]
        c_idx = None
        for j in range(len(c_slice)):
            c_row = c_slice.iloc[j]
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
        for j in range(len(d_slice)):
            curr_idx = c_idx + 1 + j
            d_row = d_slice.iloc[j]
            d_close = float(d_row['close'])
            d_open = float(d_row['open'])

            # Standard 100% Candle Close check: Close > Benchmark
            if d_close > benchmark:
                d_idx = curr_idx
                break

            # Near-Close Live Candle D check with Dual Guards (applied ONLY to current active forming candle)
            if curr_idx == len(df_entry) - 1:
                tf_to_check = entry_tf or anchor_tf
                if tf_to_check and is_live_candle_near_close(d_row.get('date'), tf_to_check, completion_pct=0.90):
                    # Guard 1: Benchmark Buffer Guard (+0.3%)
                    if d_close >= (benchmark * 1.003):
                        # Guard 2: Volume Validation Guard (80% of 20-period avg volume)
                        vol_passed = True
                        if 'volume' in df_entry.columns and curr_idx >= 20:
                            avg_vol_20 = float(df_entry['volume'].iloc[curr_idx - 20 : curr_idx].mean())
                            curr_vol = float(d_row.get('volume', 0))
                            if avg_vol_20 > 0 and curr_vol < (0.80 * avg_vol_20):
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
            # 4. Check if T1 has been reached after D
            if float(after_d['close'].max()) >= t1:
                # If T3 reached or T2 reached or no T2/T3 available -> All targets completed -> Discard
                if (t3 is not None and float(after_d['close'].max()) >= t3) or t2 is None or float(after_d['close'].max()) >= t2:
                    continue
                # T1 was hit, but T2/T3 is still pending -> Qualifies as LOW PRIORITY T2 Continuation if intact
                stage_status = "T2_CONTINUATION"
                priority_level = "LOW_PRIORITY"
                sl_val = t1  # Trailed SL to T1 level to protect banked gains

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
            "d_idx": d_idx
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

    # Option A Balanced Tiering (T1 Gold 1:2 / 2.0, T2 Core 1:1.5 / 1.5):
    # Tier 1 (Gold): Strictly 5 True Anchors + (>=3 Waves or Tier 1 Multi-Swing Arch) + R:R >= 2.0
    # Tier 2 (Core): 5 True Anchors (>=2 Waves / R:R >= 1.5) OR strong BASE_ABCD with (>=3 Waves and R:R >= 2.0)
    # Tier 3 (Momentum): Standard/early BASE_ABCD and trend continuations (R:R >= 1.5)
    if is_true_anchor and (sw_waves >= 3 or swing_meta.get("tier") == 1) and rr_val >= 2.0:
        tier = 1
        tier_label = "TIER_1_GOLD"
        tier_badge = "🥇 T1"
    elif (is_true_anchor and (sw_waves >= 2 or p_rank >= 3 or rr_val >= 1.5)) or ((sw_waves >= 3 or swing_meta.get("tier") == 1) and rr_val >= 2.0):
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
    return best_latest



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
        "D_time": str(current_candle.get("date", "")),
        "A_time": str(trigger_candle.get("date", "")),
        "tier": 3,
        "tier_label": "TIER_3_MOMENTUM",
        "tier_badge": "🥉 T3",
        "swing_waves": 1,
        "terminal_base": False
    }
