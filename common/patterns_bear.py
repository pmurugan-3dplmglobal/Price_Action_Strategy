"""
Bearish price action pattern detectors: 5 anchor patterns (engulfing, HH sweep,
shooting star baby, harami, two lower lows), A-B-C-D breakout scanner, bearish
trend continuation re-entry (Page 17), and the unified generic scanner.
Extracted from trading_core.py (2026-08-11).
"""
import logging
import pandas as pd
from datetime import datetime as dt

from targets import (
    find_profit_targets_bearish, check_left_side_rule_bearish,
    calculate_sl_buffer
)
from timeframe_utils import get_adaptive_lookback, resample_timeframe, trading_days_between, is_live_candle_near_close
from swing_detection import (
    is_parabolic_arch_enhanced,
    extract_swing_pivots,
    validate_parabolic_cascade_structure,
    detect_parabolic_multi_swings
)

def find_anchor_bearish_engulfing(df):
    """Setup 1 (Bearish): A = bearish engulfing candle. Bullish candle-1, then bearish candle wrapping body+wick."""
    if len(df) < 5:
        return None
    bullish_candle, bear_anchor = df.iloc[-4], df.iloc[-3]
    if not (float(bullish_candle['close']) > float(bullish_candle['open'])):
        return None
    if not (float(bear_anchor['close']) < float(bear_anchor['open'])):
        return None
    if not (float(bear_anchor['open']) >= float(bullish_candle['close']) and float(bear_anchor['close']) < float(bullish_candle['low'])):
        return None
    a_high = float(bear_anchor['high'])
    anchor_close = float(bear_anchor['close'])
    sl_val = calculate_sl_buffer(a_high, side="BEAR")
    return {"Pattern": "BEAR_A_ABCD_Engulf", "Close": anchor_close, "SL": sl_val, "Signal": "Bear_A_Formation", "CandleATime": str(bear_anchor.get('date', ''))}

def find_anchor_hh_sweep(df):
    """
    Setup 2 (Bearish): A = High 2 (sweep above prior swing high High 1).
    Rules:
      1. Need > 2 candles (at least 3 candles gap) between High 1 and High 2.
      2. In-between candles must NOT close above High 1 (wicks allowed).
      3. High 2 sweeps above High 1.
    """
    if len(df) < 30:
        return None

    search_range = df.iloc[-29:-7]
    if search_range.empty:
        return None

    high_1_idx = search_range['high'].idxmax()
    high_1 = float(df.loc[high_1_idx, 'high'])

    sweep_idx = df.index[-4]

    pos_high_1 = df.index.get_loc(high_1_idx)
    pos_sweep = df.index.get_loc(sweep_idx)
    if (pos_sweep - pos_high_1 - 1) < 3:
        return None

    inbetween_df = df.iloc[pos_high_1 + 1 : pos_sweep]
    if not inbetween_df.empty:
        if (inbetween_df['close'] > high_1).any():
            return None

    # Calculate ATR for intermediate swing pullback check (Datta Swing criteria: visible pullback between H1 and H2)
    high_low_diff = (df['high'] - df['low']).abs()
    atr = float(high_low_diff.iloc[max(0, pos_sweep - 14) : pos_sweep].mean()) if len(df) >= 14 else (high_1 * 0.02)
    if atr <= 0:
        atr = high_1 * 0.02

    # Intermediate Swing Requirement: In-between candles must show a distinct swing pullback (>= 0.8x ATR or >= 1.5%)
    inbetween_low = float(inbetween_df['low'].min()) if not inbetween_df.empty else high_1
    min_pullback_req = high_1 - max(0.8 * atr, high_1 * 0.015)
    if inbetween_low > min_pullback_req:
        return None

    sweep_candle, rejection_candle, confirm_candle_1, confirm_candle_2 = df.iloc[-4], df.iloc[-3], df.iloc[-2], df.iloc[-1]
    sweep_high = float(sweep_candle['high'])
    is_green = float(sweep_candle['close']) > float(sweep_candle['open'])
    is_red = float(sweep_candle['close']) <= float(sweep_candle['open'])

    # Var 1: Green sweep candle (sweeps/closes above High 1, rejected back down)
    v1 = is_green and (sweep_high > high_1) and (float(sweep_candle['close']) < high_1)
    v2 = is_green and (float(sweep_candle['close']) > high_1) and (float(rejection_candle['close']) < high_1)

    # Var 2: Red/Neutral wick sweep candle (upper wick pierces High 1, body closes red below High 1)
    v3 = is_red and (sweep_high > high_1) and (float(sweep_candle['close']) < high_1)

    if not (v1 or v2 or v3):
        return None
    if not (float(rejection_candle['close']) < float(sweep_candle['low'])):
        return None
    if float(confirm_candle_1['close']) > sweep_high or float(confirm_candle_2['close']) > sweep_high:
        return None

    pattern_name = "BEAR_A_HH_Sweep_Var1" if (v1 or v2) else "BEAR_A_HH_Sweep_Var2"

    anchor_close = float(rejection_candle['close'])
    sl_val = calculate_sl_buffer(sweep_high, side="BEAR")
    return {"Pattern": pattern_name, "Close": anchor_close, "SL": sl_val, "Signal": "High2_Formation", "CandleATime": str(sweep_candle.get('date', ''))}

def find_anchor_two_lower_lows(df):
    """Setup 3 (Bearish): A1 & A2 are two successive lower low bearish candles."""
    if len(df) < 5:
        return None
    a1, a2 = df.iloc[-4], df.iloc[-3]
    if not (float(a1['close']) < float(a1['open']) and float(a2['close']) < float(a2['open'])):
        return None
    if not (float(a2['low']) < float(a1['low']) and float(a2['high']) < float(a1['high'])):
        return None
    a_high = max(float(a1['high']), float(a2['high']))
    anchor_close = float(a2['close'])
    sl_val = calculate_sl_buffer(a_high, side="BEAR")
    return {"Pattern": "BEAR_A_Two_Lower_Lows", "Close": anchor_close, "SL": sl_val, "Signal": "LowerLow_Engulf", "CandleATime": str(a2.get('date', ''))}

def find_anchor_shooting_star_baby(df):
    """Setup 4 (Bearish): A = shooting star / baby candle inside/at bullish mother peak with strong upper wick rejection."""
    if len(df) < 5:
        return None
    mother_candle, baby_candle, post_baby_1, post_baby_2, post_baby_3 = df.iloc[-5], df.iloc[-4], df.iloc[-3], df.iloc[-2], df.iloc[-1]
    if not (float(mother_candle['close']) > float(mother_candle['open'])):
        return None
    is_red = float(baby_candle['close']) <= float(baby_candle['open'])
    b_open = float(baby_candle['open'])
    b_close = float(baby_candle['close'])
    b_high = float(baby_candle['high'])
    b_low = float(baby_candle['low'])

    total_range = b_high - b_low
    if total_range <= 0:
        return None

    body = abs(b_close - b_open)
    upper_wick = b_high - max(b_open, b_close)
    lower_wick = min(b_open, b_close) - b_low

    # 1. Upper wick must be dominant relative to body (at least 1.2x for red, 1.8x for green)
    min_wick_ratio = 1.2 if is_red else 1.8
    if upper_wick < (body * min_wick_ratio):
        return None
    if upper_wick <= lower_wick:
        return None

    # 2. Lower wick cap: Lower wick must not exceed 35% of total candle range or 50% of upper wick (filters spinning tops)
    if lower_wick > (total_range * 0.35) or lower_wick > (upper_wick * 0.50):
        return None

    # 3. Close conviction: Close must finish in lower 40% of the total candle span (<= 0.40 from low)
    close_position = (b_close - b_low) / total_range
    if close_position > 0.40:
        return None

    # 4. Multi-bar stability guard: Subsequent candles must not breach the anchor high
    if float(post_baby_2['close']) > b_high or float(post_baby_3['close']) > b_high:
        return None

    anchor_close = b_close
    sl_val = calculate_sl_buffer(b_high, side="BEAR")
    return {"Pattern": "BEAR_A_ShootingStar_Baby", "Close": anchor_close, "SL": sl_val, "Signal": "ShootingStar_Formation", "CandleATime": str(baby_candle.get('date', ''))}

def find_anchor_bearish_harami(df):
    """Setup 5 (Bearish): A = bearish inside bar fully inside bullish mother body."""
    if len(df) < 5:
        return None
    bullish_mother, bearish_inside, post_harami_1, post_harami_2, post_harami_3 = df.iloc[-5], df.iloc[-4], df.iloc[-3], df.iloc[-2], df.iloc[-1]
    if not (float(bullish_mother['close']) > float(bullish_mother['open']) and float(bearish_inside['close']) < float(bearish_inside['open'])):
        return None
    if not (float(bearish_inside['high']) <= float(bullish_mother['close']) and float(bearish_inside['low']) >= float(bullish_mother['open'])):
        return None
    inside_high = float(bearish_inside['high'])
    if float(post_harami_2['close']) > inside_high or float(post_harami_3['close']) > inside_high:
        return None
    anchor_close = float(bearish_inside['close'])
    sl_val = calculate_sl_buffer(inside_high, side="BEAR")
    return {"Pattern": "BEAR_A_Harami", "Close": anchor_close, "SL": sl_val, "Signal": "Bear_Harami_Formation", "CandleATime": str(bearish_inside.get('date', ''))}


# ──────────────────────────────────────────────
#  BEARISH BREAKOUT SCANNER (A -> B -> C -> D)
# ──────────────────────────────────────────────

def scan_anchor_bcd_breakout_bearish(df_entry, df_anchor, anchor_tf="", entry_tf="", enable_swing_filter=None, swing_min_waves=3, swing_min_r2=0.55):
    """
    Two-phase A-first Bearish scanner with Institutional Phase 0 Parabolic Multi-Swing Filter:
      Phase 0: Multi-Swing Parabolic decay fitting (>= 3 waves, R^2 >= 0.55) & Terminal Base on df_anchor.
      Phase 1: Find anchor candle A (at or after the terminal base high).
      Phase 2: From A, scan forward sequentially: B (breakout < A.low) ->
               C (green retest) -> D (confirmation close < A.low).
    """
    if df_entry is None or df_entry.empty or df_anchor is None or df_anchor.empty:
        return None

    if len(df_anchor) < 10 or len(df_entry) < 10:
        return None

    swing_meta = {"swing_waves": 0, "terminal_base": False, "terminal_date": ""}
    if enable_swing_filter is None:
        try:
            import json, paths, os
            if os.path.exists(paths.PROGRAM_CONFIG_FILE):
                with open(paths.PROGRAM_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg_all = json.load(f)
                enable_swing_filter = bool(cfg_all.get("bear_trade", {}).get("enable_swing_filter", True))
                swing_min_waves = int(cfg_all.get("bear_trade", {}).get("swing_min_waves", swing_min_waves))
                swing_min_r2 = float(cfg_all.get("bear_trade", {}).get("swing_min_r2", swing_min_r2))
        except Exception:
            enable_swing_filter = False

    if enable_swing_filter:
        sw_res = detect_parabolic_multi_swings(df_anchor, side="BEAR", min_swings=swing_min_waves, min_r2=swing_min_r2, max_bars_after_terminal=20)
        swing_meta = {
            "swing_waves": sw_res.get("valid_arch_count", 0),
            "terminal_base": sw_res.get("has_terminal_base", False),
            "terminal_date": sw_res.get("terminal_swing_date", ""),
            "tier": sw_res.get("tier", 2),
            "tier_label": sw_res.get("tier_label", "TIER_2_CORE"),
            "tier_badge": sw_res.get("tier_badge", "🥈 T2")
        }

    detectors = [
        find_anchor_bearish_engulfing,
        find_anchor_hh_sweep,
        find_anchor_two_lower_lows,
        find_anchor_shooting_star_baby,
        find_anchor_bearish_harami
    ]

    best_match = None
    min_anchor_search_len = min(60, len(df_anchor))

    for anchor_idx in range(len(df_anchor) - 3, len(df_anchor) - min_anchor_search_len, -1):
        sub_anchor_df = df_anchor.iloc[:anchor_idx + 1]
        anchor_candle = sub_anchor_df.iloc[-1]
        
        det_result = None
        for det in detectors:
            res = det(sub_anchor_df)
            if res:
                det_result = res
                break
        
        is_bear_candle = float(anchor_candle['close']) < float(anchor_candle['open'])
        if not det_result and not is_bear_candle:
            continue

        a_high = float(anchor_candle['high'])
        a_low = float(anchor_candle['low'])
        a_close = float(anchor_candle['close'])
        a_date = det_result.get("CandleATime") if det_result and det_result.get("CandleATime") else anchor_candle.get('date', '')

        # Sequence gatekeeper: If terminal base is confirmed, Anchor A must be formed at or after terminal base date
        if swing_meta.get("terminal_base") and swing_meta.get("terminal_date") and a_date:
            if str(a_date) < str(swing_meta["terminal_date"]):
                continue

        anchor_entry_matches = df_entry[df_entry['date'] == a_date] if 'date' in df_entry.columns else pd.DataFrame()
        if anchor_entry_matches.empty:
            continue

        e_anchor_idx = anchor_entry_matches.index[0]

        if not check_left_side_rule_bearish(df_entry, a_high, setup_count=0, skip_adjacent=(len(df_entry) - 1 - e_anchor_idx)):
            continue

        b_idx = None
        for i in range(e_anchor_idx + 1, min(e_anchor_idx + 30, len(df_entry))):
            candle = df_entry.iloc[i]
            if float(candle['close']) > a_high:
                break
            if float(candle['close']) < a_low:
                b_idx = i
                break

        if b_idx is None:
            continue

        c_idx = None
        for i in range(b_idx + 1, min(b_idx + 30, len(df_entry))):
            candle = df_entry.iloc[i]
            if float(candle['close']) > a_high:
                break
            if float(candle['high']) >= a_low and float(candle['close']) < a_high:
                c_idx = i
                break

        if c_idx is None:
            continue

        d_idx = None
        is_near_close_d = False
        for i in range(c_idx + 1, min(c_idx + 30, len(df_entry))):
            candle = df_entry.iloc[i]
            c_close = float(candle['close'])
            c_open = float(candle['open'])
            is_red = c_close < c_open

            if c_close > a_high:
                break

            # Standard 100% Candle Close check
            if c_close < a_low and is_red:
                d_idx = i
                break

            # Near-Close Live Candle D check with Dual Guards (applied ONLY to current active forming candle)
            if i == len(df_entry) - 1 and is_red:
                tf_to_check = entry_tf or anchor_tf
                if tf_to_check and is_live_candle_near_close(candle.get('date'), tf_to_check, completion_pct=0.90):
                    # Guard 1: Benchmark Buffer Guard (-0.3% below benchmark for bearish)
                    if c_close <= (a_low * 0.997):
                        # Guard 2: Volume Validation Guard (80% of 20-period avg volume)
                        vol_passed = True
                        if 'volume' in df_entry.columns and i >= 20:
                            avg_vol_20 = float(df_entry['volume'].iloc[i - 20 : i].mean())
                            curr_vol = float(candle.get('volume', 0))
                            if avg_vol_20 > 0 and curr_vol < (0.80 * avg_vol_20):
                                vol_passed = False
                        if vol_passed:
                            d_idx = i
                            is_near_close_d = True
                            break

        if d_idx is None:
            continue

        intermediate_bars = df_entry.iloc[e_anchor_idx:d_idx + 1]
        if float(intermediate_bars['close'].max()) > a_high:
            continue

        pattern_type = det_result["Pattern"] if det_result else "BEAR_BASE_ABCD"
        if is_near_close_d and not pattern_type.endswith("_EARLY"):
            pattern_type += "_EARLY"

        entry_candle = df_entry.iloc[d_idx]
        entry_close = float(entry_candle['close'])
        sl_val = round(a_high + max(0.50, a_high * 0.02), 2)

        t1, t2, t3 = find_profit_targets_bearish(df_anchor, entry_close, stop_loss=sl_val)
        if not t1 or t1 >= entry_close:
            t1 = round(entry_close - max(1.5 * abs(sl_val - entry_close), entry_close * 0.05), 2)

        stage_status = "EARLY_D_ENTRY" if is_near_close_d else "FRESH_ENTRY"
        priority_level = "HIGH_PRIORITY"

        # Post-D 3-Tier Classification Filter
        after_d = df_entry.iloc[d_idx + 1 :]
        if not after_d.empty:
            # 1. Discard if SL hit after D (A.high + buffer)
            if float(after_d['close'].max()) >= sl_val:
                continue
            # 2. Check if T1 has been reached after D
            if t1 is not None and float(after_d['close'].min()) <= t1:
                # If T3 reached or T2 reached or no T2/T3 available -> All targets completed
                if (t3 is not None and float(after_d['close'].min()) <= t3) or t2 is None or float(after_d['close'].min()) <= t2:
                    continue
                # T1 was hit, but T2/T3 is still pending -> Qualifies as LOW PRIORITY T2 Continuation
                stage_status = "T2_CONTINUATION"
                priority_level = "LOW_PRIORITY"
                sl_val = t1  # Trailed SL to T1 level to protect banked gains

        risk = sl_val - entry_close
        if risk <= 0:
            continue

        rr = (entry_close - t1) / risk
        if rr < 1.88:
            continue

        setup_data = {
            "Pattern": pattern_type,
            "Close": entry_close,
            "SL": sl_val,
            "T1": t1,
            "T2": t2,
            "T3": t3,
            "RR": round(rr, 2),
            "A_Date": str(a_date),
            "D_Date": str(entry_candle.get('date', '')),
            "Benchmark": a_low,
            "AnchorFloor": a_high,
            "Direction": "BEAR",
            "Stage_Status": stage_status,
            "Priority": priority_level,
            "d_idx": d_idx
        }

        if best_match is None or setup_data["d_idx"] > best_match.get("d_idx", -1) or \
           (setup_data["d_idx"] == best_match.get("d_idx", -1) and setup_data["Priority"] == "HIGH_PRIORITY" and setup_data["RR"] > best_match.get("RR", 0)):
            best_match = setup_data

    if best_match:
        best_match.pop("d_idx", None)
        sw_waves = swing_meta.get("swing_waves", 0)
        term_base = swing_meta.get("terminal_base", False)
        rr_val = float(best_match.get("RR", 0.0))
        pat_name = str(best_match.get("Pattern", ""))
        p_is_strong = any(k in pat_name for k in ["Engulf", "HH_Sweep", "Star", "Baby"])

        if (sw_waves >= 3 or swing_meta.get("tier") == 1) and rr_val >= 2.5:
            tier = 1
            tier_label = "TIER_1_GOLD"
            tier_badge = "🥇 T1"
        elif sw_waves >= 2 or p_is_strong or rr_val >= 1.88:
            tier = 2
            tier_label = "TIER_2_CORE"
            tier_badge = "🥈 T2"
        else:
            tier = 3
            tier_label = "TIER_3_MOMENTUM"
            tier_badge = "🥉 T3"

        best_match["tier"] = tier
        best_match["tier_label"] = tier_label
        best_match["tier_badge"] = tier_badge
        best_match["swing_waves"] = sw_waves
        best_match["terminal_base"] = term_base
    return best_match


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
    if risk <= 0 or risk < entry_price * 0.002 or ((t1 - entry_price) / risk) < 1.88:
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

def scan_trend_continuation_reentry_bearish(df_entry, df_anchor):
    """
    Setup Page 17 (Bearish Trend Continuation + Re-Entry):
    1. Context: Established Downtrend (Lower Highs & Lower Lows in preceding window).
    2. Retest: Price pulls back to prior swing resistance level.
    3. Trigger: Bearish Engulfing or Rejection candle forms at resistance.
    4. Execution: Immediate Re-entry / Short on the next candle close (No BCD delay).
    """
    if len(df_entry) < 20:
        return None

    lookback = df_entry.iloc[-25:-2]
    if lookback.empty or len(lookback) < 10:
        return None

    mid_point = len(lookback) // 2
    part1 = lookback.iloc[:mid_point]
    part2 = lookback.iloc[mid_point:]

    if not (part2['high'].max() < part1['high'].max() and part2['low'].min() < part1['low'].min()):
        return None

    trigger_candle = df_entry.iloc[-2]
    current_candle = df_entry.iloc[-1]

    is_red_trigger = float(trigger_candle['close']) < float(trigger_candle['open'])
    if not is_red_trigger:
        return None

    resistance_level = float(part2['high'].max())
    trigger_high = float(trigger_candle['high'])
    trigger_close = float(trigger_candle['close'])

    if not (trigger_high >= (resistance_level * 0.985) and trigger_close <= resistance_level):
        return None

    entry_price = float(current_candle['close'])
    sl_val = round(trigger_high + max(0.50, trigger_high * 0.02), 2)

    if entry_price >= sl_val:
        return None

    t1, t2, t3 = find_profit_targets_bearish(df_anchor, entry_price, stop_loss=sl_val)
    if t1 is None or t1 >= entry_price:
        return None

    risk = sl_val - entry_price
    if risk <= 0 or risk < entry_price * 0.002 or ((entry_price - t1) / risk) < 1.88:
        return None

    rr = (entry_price - t1) / risk
    return {
        "Pattern": "TREND_CONT_BEAR",
        "SL": sl_val,
        "T1": t1,
        "T2": t2,
        "T3": t3,
        "Entry": entry_price,
        "RR": round(rr, 2),
        "Signal": "Immediate_ReEntry_Bear",
        "D_time": str(current_candle.get("date", "")),
        "A_time": str(trigger_candle.get("date", "")),
        "tier": 3,
        "tier_label": "TIER_3_MOMENTUM",
        "tier_badge": "🥉 T3",
        "swing_waves": 1,
        "terminal_base": False
    }

def scan_anchor_bcd_breakout_generic(df_entry, df_anchor, side="BULL", anchor_tf="", entry_tf=""):
    """
    Unified A-first breakout scanner supporting both BULLISH and BEARISH reversals,
    plus fast Trend Continuation Re-entries (Pages 16 & 17).
    """
    if str(side).upper() == "BEAR":
        res = scan_anchor_bcd_breakout_bearish(df_entry, df_anchor, anchor_tf=anchor_tf, entry_tf=entry_tf)
        if not res:
            res = scan_trend_continuation_reentry_bearish(df_entry, df_anchor)
        return res
    else:
        res = scan_anchor_bcd_breakout(df_entry, df_anchor, anchor_tf=anchor_tf, entry_tf=entry_tf)
        if not res:
            res = scan_trend_continuation_reentry(df_entry, df_anchor)
        return res




