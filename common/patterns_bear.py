"""
Bearish price action pattern detectors: 5 anchor patterns (engulfing, HH sweep,
shooting star baby, harami, two lower lows), A-B-C-D breakout scanner, bearish
trend continuation re-entry (Page 17), and the unified generic scanner.
Extracted from trading_core.py (2026-08-11).
"""
import os, sys
COMMON_DIR = os.path.dirname(os.path.abspath(__file__))
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

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
    if len(df) < 2:
        return None
    bullish_candle, bear_anchor = df.iloc[-2], df.iloc[-1]
    if not (float(bullish_candle['close']) > float(bullish_candle['open'])):
        return None
    if not (float(bear_anchor['close']) < float(bear_anchor['open'])):
        return None
    if not (float(bear_anchor['open']) >= float(bullish_candle['close']) and float(bear_anchor['close']) < float(bullish_candle['low'])):
        return None
    a_high = float(bear_anchor['high'])
    a_low = float(bear_anchor['low'])
    anchor_close = float(bear_anchor['close'])
    sl_val = calculate_sl_buffer(a_high, side="BEAR")
    return {
        "Pattern": "BEAR_A_ABCD_Engulf",
        "Close": anchor_close,
        "SL": sl_val,
        "AnchorHigh": a_high,
        "AnchorLow": a_low,
        "Signal": "Bear_A_Formation",
        "CandleATime": str(bear_anchor.get('date', ''))
    }

def find_anchor_hh_sweep(df):
    """
    Setup 2 (Bearish): A = High 2 (sweep above prior swing high High 1).
    Rules:
      1. Need > 2 candles (at least 3 candles gap) between High 1 and High 2.
      2. In-between candles must NOT close above High 1 (wicks allowed).
      3. High 2 sweeps above High 1.
    """
    if len(df) < 8:
        return None

    search_range = df.iloc[:-2]
    if search_range.empty or len(search_range) < 4:
        return None

    high_1_idx = search_range['high'].idxmax()
    high_1 = float(df.loc[high_1_idx, 'high'])

    sweep_candle, rejection_candle = df.iloc[-2], df.iloc[-1]
    sweep_idx = sweep_candle.name

    pos_high_1 = df.index.get_loc(high_1_idx)
    pos_sweep = df.index.get_loc(sweep_idx)
    if (pos_sweep - pos_high_1 - 1) < 2:
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

    pattern_name = "BEAR_A_HH_Sweep_Var1" if (v1 or v2) else "BEAR_A_HH_Sweep_Var2"

    anchor_close = float(rejection_candle['close'])
    anchor_low = min(float(sweep_candle['low']), float(rejection_candle['low']))
    sl_val = calculate_sl_buffer(sweep_high, side="BEAR")
    return {
        "Pattern": pattern_name,
        "Close": anchor_close,
        "SL": sl_val,
        "AnchorHigh": sweep_high,
        "AnchorLow": anchor_low,
        "Signal": "High2_Formation",
        "CandleATime": str(sweep_candle.get('date', ''))
    }

def find_anchor_two_lower_lows(df):
    """Setup 3 (Bearish): A1 & A2 are two successive lower low bearish candles."""
    if len(df) < 2:
        return None
    a1, a2 = df.iloc[-2], df.iloc[-1]
    if not (float(a1['close']) < float(a1['open']) and float(a2['close']) < float(a2['open'])):
        return None
    if not (float(a2['low']) < float(a1['low']) and float(a2['high']) < float(a1['high'])):
        return None
    a_high = max(float(a1['high']), float(a2['high']))
    a_low = min(float(a1['low']), float(a2['low']))
    anchor_close = float(a2['close'])
    sl_val = calculate_sl_buffer(a_high, side="BEAR")
    return {
        "Pattern": "BEAR_A_Two_Lower_Lows",
        "Close": anchor_close,
        "SL": sl_val,
        "AnchorHigh": a_high,
        "AnchorLow": a_low,
        "Signal": "LowerLow_Engulf",
        "CandleATime": str(a2.get('date', ''))
    }

def find_anchor_shooting_star_baby(df):
    """Setup 4 (Bearish): A = shooting star / baby candle inside/at bullish mother peak with strong upper wick rejection."""
    if len(df) < 2:
        return None
    mother_candle, baby_candle = df.iloc[-2], df.iloc[-1]
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

    # 4. Containment / Location: Star must test the peak/upper region of the bullish mother candle
    m_close = float(mother_candle['close'])
    if b_high < (m_close * 0.995):
        return None

    anchor_close = b_close
    sl_val = calculate_sl_buffer(b_high, side="BEAR")
    return {
        "Pattern": "BEAR_A_ShootingStar_Baby",
        "Close": anchor_close,
        "SL": sl_val,
        "AnchorHigh": b_high,
        "AnchorLow": b_low,
        "Signal": "ShootingStar_Formation",
        "CandleATime": str(baby_candle.get('date', ''))
    }

def find_anchor_bearish_harami(df):
    """Setup 5 (Bearish): A = bearish inside bar fully inside bullish mother body."""
    if len(df) < 2:
        return None
    bullish_mother, bearish_inside = df.iloc[-2], df.iloc[-1]
    m_open, m_close = float(bullish_mother['open']), float(bullish_mother['close'])
    i_open, i_close = float(bearish_inside['open']), float(bearish_inside['close'])
    if not (m_close > m_open and i_close < i_open):
        return None
    if not (float(bearish_inside['high']) <= m_close and float(bearish_inside['low']) >= m_open):
        return None
    # Body size ratio check: Inside body must be <= 65% of mother body (Datta rulebook)
    mother_body = m_close - m_open
    inside_body = i_open - i_close
    if mother_body > 0 and (inside_body / mother_body) > 0.65:
        return None
    inside_high = float(bearish_inside['high'])
    inside_low = float(bearish_inside['low'])
    anchor_close = i_close
    sl_val = calculate_sl_buffer(inside_high, side="BEAR")
    return {
        "Pattern": "BEAR_A_Harami",
        "Close": anchor_close,
        "SL": sl_val,
        "AnchorHigh": inside_high,
        "AnchorLow": inside_low,
        "Signal": "Bear_Harami_Formation",
        "CandleATime": str(bearish_inside.get('date', ''))
    }


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
        sw_res = detect_parabolic_multi_swings(df_anchor, side="BEAR", min_swings=swing_min_waves, min_r2=swing_min_r2, max_bars_after_terminal=45, timeframe_str=anchor_tf)
        swing_meta = {
            "swing_waves": sw_res.get("valid_arch_count", 0),
            "terminal_base": sw_res.get("has_terminal_base", False),
            "terminal_date": sw_res.get("terminal_swing_date", ""),
            "terminal_idx": sw_res.get("terminal_swing_idx"),
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

    for anchor_idx in range(len(df_anchor) - 1, len(df_anchor) - min_anchor_search_len, -1):
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

        a_high = float(det_result.get("AnchorHigh", anchor_candle['high'])) if det_result else float(anchor_candle['high'])
        a_low = float(det_result.get("AnchorLow", anchor_candle['low'])) if det_result else float(anchor_candle['low'])
        a_close = float(anchor_candle['close'])
        a_date = det_result.get("CandleATime") if det_result and det_result.get("CandleATime") else anchor_candle.get('date', '')

        # Sequence gatekeeper: Allow Anchor A to form within the terminal base window (allowing 5-bar lookback for base confirmation)
        if swing_meta.get("terminal_base") and swing_meta.get("terminal_date") and a_date:
            term_idx = swing_meta.get("terminal_idx")
            if term_idx is not None:
                if anchor_idx < max(0, term_idx - 5):
                    continue
            else:
                try:
                    a_dt = pd.to_datetime(str(a_date).split("+")[0])
                    t_dt = pd.to_datetime(str(swing_meta["terminal_date"]).split("+")[0])
                    if (t_dt - a_dt).days > 8:
                        continue
                except Exception:
                    pass

        e_anchor_idx = None
        if 'date' in df_entry.columns:
            exact_matches = df_entry[df_entry['date'] == a_date]
            if not exact_matches.empty:
                e_anchor_idx = exact_matches.index[0]
            else:
                # Normalized prefix comparison (e.g. YYYY-MM-DD) for multi-timeframe scans
                a_str = str(a_date).split("T")[0].split(" ")[0].strip()
                if len(a_str) >= 10:
                    for ei in range(len(df_entry)):
                        e_str = str(df_entry.iloc[ei].get('date', '')).split("T")[0].split(" ")[0].strip()
                        if e_str == a_str:
                            e_anchor_idx = ei
                            break
        else:
            e_anchor_idx = anchor_idx

        if e_anchor_idx is None:
            continue

        if not check_left_side_rule_bearish(df_entry, a_high, setup_count=0, skip_adjacent=(len(df_entry) - 1 - e_anchor_idx)):
            continue

        b_idx = None
        for i in range(e_anchor_idx + 1, min(e_anchor_idx + 60, len(df_entry))):
            candle = df_entry.iloc[i]
            if float(candle['close']) > a_high:
                break
            if float(candle['close']) < a_low:
                b_idx = i
                break

        if b_idx is None:
            continue

        c_idx = None
        risk_dist = max(0.50, a_high - a_low)
        min_b_excursion = a_low - (1.5 * risk_dist)
        try:
            t1_target, _, _ = find_profit_targets_bearish(df_anchor, a_low, stop_loss=a_high)
            if t1_target is not None and t1_target < a_low:
                min_b_excursion = max(min_b_excursion, float(t1_target))
        except Exception:
            pass

        for i in range(b_idx + 1, min(b_idx + 26, len(df_entry))):
            candle = df_entry.iloc[i]
            # Excursion guard: If price already dropped > 1.5x risk below benchmark, move is exhausted
            if float(candle['low']) < min_b_excursion:
                break
            c_close = float(candle['close'])
            c_open = float(candle['open'])
            c_high = float(candle['high'])
            is_green = c_close > c_open
            if c_close > a_high:
                break
            # Point C Retest: Must test broken benchmark a_low with green retest candle
            # or green rejection upper wick, holding below a_high ceiling (exact parity with Bull Point C)
            if ((c_high >= a_low and c_close <= a_high and is_green) or
                (c_high >= a_high and c_close <= a_high and c_close > float(anchor_candle['open']) and is_green)):
                c_idx = i
                break

        if c_idx is None:
            continue

        d_idx = None
        is_near_close_d = False
        for i in range(c_idx + 1, min(c_idx + 60, len(df_entry))):
            candle = df_entry.iloc[i]
            c_close = float(candle['close'])
            c_open = float(candle['open'])
            is_red = c_close < c_open

            if c_close > a_high:
                break

            # Case A: Completed Historical Candle (100% closed)
            if i < len(df_entry) - 1:
                if c_close < a_low:
                    d_idx = i
                    break

            # Case B: Current Live Active Forming Candle (near-close >= 80% with dual guards)
            else:
                tf_to_check = entry_tf or anchor_tf
                if tf_to_check and is_live_candle_near_close(candle.get('date'), tf_to_check, completion_pct=0.80):
                    # Guard 1: Benchmark Buffer Guard (-0.3% below benchmark for bearish)
                    if c_close <= (a_low * 0.997):
                        # Guard 2: Proportional Volume Validation Guard (60% of 20-period avg volume at 80% time)
                        vol_passed = True
                        if 'volume' in df_entry.columns and i >= 20:
                            avg_vol_20 = float(df_entry['volume'].iloc[i - 20 : i].mean())
                            curr_vol = float(candle.get('volume', 0))
                            if avg_vol_20 > 0 and curr_vol < (0.60 * avg_vol_20):
                                vol_passed = False
                        if vol_passed:
                            d_idx = i
                            is_near_close_d = True
                            break

        if d_idx is None:
            continue

        candles_since_d = len(df_entry) - 1 - d_idx
        if candles_since_d > 60:
            continue

        intermediate_bars = df_entry.iloc[e_anchor_idx:d_idx + 1]
        if float(intermediate_bars['close'].max()) > a_high:
            continue

        pattern_type = det_result["Pattern"] if det_result else "BEAR_BASE_ABCD"
        if is_near_close_d and not pattern_type.endswith("_EARLY"):
            pattern_type += "_EARLY"

        entry_candle = df_entry.iloc[d_idx]
        entry_close = float(entry_candle['close'])
        sl_val = det_result.get("SL") if (det_result and det_result.get("SL")) else calculate_sl_buffer(a_high, side="BEAR")

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
            # 2. Check if T1 (or 80% T1) has been reached after D
            t1_80 = entry_close - 0.80 * (entry_close - t1)
            if t1 is not None and (float(after_d['low'].min()) <= t1_80 or float(after_d['close'].min()) <= t1):
                t2_gap_pct = ((t1 - t2) / t1) if (t2 is not None and t1 > 0) else 0.0
                # If T3 reached, T2 reached, no T2 available, or T2 has less gap (< 10%) -> Discard scan
                if (t3 is not None and float(after_d['close'].min()) <= t3) or t2 is None or t2_gap_pct < 0.10 or float(after_d['close'].min()) <= t2:
                    continue
                # T1 was hit with sufficient T2 room -> Qualifies as LOW PRIORITY T2 Continuation
                stage_status = "T2_CONTINUATION"
                priority_level = "LOW_PRIORITY"
                sl_val = t1  # Trailed SL to T1 level to protect banked gains

        risk = sl_val - entry_close
        if risk <= 0:
            continue

        rr = (entry_close - t1) / risk
        if round(rr, 2) < 1.5:
            continue

        # ── Volume Profile Analysis on B-C-D (Bearish Breakdown) ──
        vol_b_ratio = 1.0
        vol_c_ratio = 1.0
        vol_d_ratio = 1.0
        vol_confirmed = True
        vol_profile_score = 3
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

                    # Retest Volume Dry-up: VC should ideally be lower than VB (pullback on declining volume)
                    # Trigger Volume Expansion: VD should be expanding relative to 20-period avg
                    is_c_dryup = (vol_c_ratio <= 0.90) or (vc <= avg_vol_20)
                    is_d_expansion = (vol_d_ratio >= 1.0) or (is_near_close_d and vol_d_ratio >= 0.60)
                    vol_confirmed = bool(is_c_dryup and is_d_expansion)

                    if vol_confirmed and vol_d_ratio >= 1.3:
                        vol_profile_score = 5
                    elif vol_confirmed:
                        vol_profile_score = 4
                    elif is_c_dryup or is_d_expansion:
                        vol_profile_score = 3
                    else:
                        vol_profile_score = 2
            except Exception:
                pass

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
            "d_idx": d_idx,
            "vol_b_ratio": vol_b_ratio,
            "vol_c_ratio": vol_c_ratio,
            "vol_d_ratio": vol_d_ratio,
            "vol_confirmed": vol_confirmed,
            "vol_score": vol_profile_score
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
        p_is_strong = any(k in pat_name for k in ["BE_ABCD", "HH_ABCD", "STAR_ABCD", "HARAMI_ABCD", "LL_ABCD"])
        is_true_anchor = p_is_strong and "BASE_ABCD" not in pat_name
        is_higher_timeframe = str(anchor_tf).lower() in ["day", "week", "1d", "1w", "daily", "weekly", "d", "w"]

        # Option A Balanced Tiering (T1 Gold 1:2 / 2.0, T2 Core 1:1.5 / 1.5):
        # Tier 1 (Gold): 
        #   - Intraday Options: Strictly 5 True Anchors + (>=3 Waves or Tier 1 Multi-Swing Arch) + R:R >= 2.0
        #   - Daily/Weekly Equities: True Anchor / Institutional Distribution Top + R:R >= 2.0
        # Tier 2 (Core): 5 True Anchors (>=2 Waves / R:R >= 1.5) OR strong BASE_ABCD with (>=3 Waves and R:R >= 2.0) OR Higher TF with R:R >= 1.5
        # Tier 3 (Momentum): Standard/early BASE_ABCD and trend continuations (R:R >= 1.5)
        if (is_true_anchor or is_higher_timeframe) and rr_val >= 2.0 and (sw_waves >= 2 or is_higher_timeframe or swing_meta.get("tier") == 1):
            tier = 1
            tier_label = "TIER_1_GOLD"
            tier_badge = "🥇 T1"
        elif (is_true_anchor and (sw_waves >= 2 or p_is_strong or rr_val >= 1.5)) or ((sw_waves >= 3 or swing_meta.get("tier") == 1) and rr_val >= 2.0) or (is_higher_timeframe and rr_val >= 1.5):
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
        try:
            from swing_detection import calculate_vcp_metrics
        except ImportError:
            from common.swing_detection import calculate_vcp_metrics
        vcp_m = calculate_vcp_metrics(df_entry)
        best_match["atr_ratio"] = vcp_m.get("atr_ratio", 1.0)
        best_match["is_squeeze"] = vcp_m.get("is_squeeze", False)
        best_match["vcp_tier"] = vcp_m.get("vcp_tier", "NORMAL")
        best_match["vcp_badge"] = vcp_m.get("vcp_badge", "")
    return best_match


def scan_pattern_lifecycle_stage_bearish(df_entry, df_anchor, anchor_tf="", entry_tf="", enable_swing_filter=None, swing_min_waves=3, swing_min_r2=0.55):
    """
    Evaluates the current maturity of a bearish symbol across the 4-stage lifecycle funnel:
      1. STAGE_FULL_ABCD: D breakdown confirmed or near-close triggered (Ready for immediate execution).
      2. STAGE_A_PLUS_READY: Phase 0 Parabolic (>= 3 waves, R^2 >= 0.55, Terminal Base) + A + B + C formed. Coiled at D trigger.
      3. STAGE_A_READY: Valid Bearish Anchor A + Breakdown B + Retest C formed. Waiting for D trigger.
      4. STAGE_B_ANCHOR: Valid Anchor A formed (Engulfing, HH Sweep, Shooting Star, Harami, Two LL, Base). B/C developing.
    Returns: dict with stage details, or None.
    """
    if df_entry is None or df_entry.empty or df_anchor is None or df_anchor.empty:
        return None

    # Step 1: Check if Full ABCD breakdown has already triggered
    full_setup = scan_anchor_bcd_breakout_bearish(
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
            "vcp_badge": full_setup.get("vcp_badge", "")
        }

    try:
        from swing_detection import calculate_vcp_metrics
    except ImportError:
        from common.swing_detection import calculate_vcp_metrics
    vcp_metrics = calculate_vcp_metrics(df_entry)

    # Step 2: Evaluate Institutional Parabolic Multi-Swing context on Anchor TF
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
        sw_res = detect_parabolic_multi_swings(df_anchor, side="BEAR", min_swings=swing_min_waves, min_r2=swing_min_r2, max_bars_after_terminal=45, timeframe_str=anchor_tf)
        swing_meta = {
            "swing_waves": sw_res.get("valid_arch_count", 0),
            "terminal_base": sw_res.get("has_terminal_base", False),
            "terminal_date": sw_res.get("terminal_swing_date", ""),
            "terminal_idx": sw_res.get("terminal_swing_idx"),
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

    short_names = {
        "BEAR_A_ABCD_Engulf": "BE_ABCD",
        "BEAR_A_HH_Sweep": "HH_ABCD",
        "BEAR_A_Two_Lower_Lows": "LL_ABCD",
        "BEAR_A_Baby_Shooting_Star": "STAR_ABCD",
        "BEAR_A_Harami": "HARAMI_ABCD"
    }

    latest_close = float(df_entry.iloc[-1]['close'])

    for anchor_idx in range(len(df_entry) - 2, max(0, len(df_entry) - 75), -1):
        sub_anchor_df = df_entry.iloc[:anchor_idx + 1]
        anchor_candle = sub_anchor_df.iloc[-1]
        
        det_result = None
        for det in detectors:
            res = det(sub_anchor_df)
            if res:
                det_result = res
                break
        
        if not det_result:
            continue

        a_high = float(det_result.get("AnchorHigh", anchor_candle['high']))
        a_low = float(det_result.get("AnchorLow", anchor_candle['low']))
        invalidation = det_result["SL"] if "SL" in det_result else calculate_sl_buffer(a_high, side="BEAR")
        anchor_name = det_result["Pattern"]
        pattern_label = short_names.get(anchor_name, "BASE_ABCD")
        a_date = str(det_result.get("CandleATime") or anchor_candle.get('date', ''))

        # Invalidation check: Price must not have closed above invalidation post-A
        after_a = df_entry.iloc[anchor_idx + 1:]
        if not after_a.empty and float(after_a['close'].max()) >= invalidation:
            continue
        if latest_close >= invalidation:
            continue

        # Check Point B: breakdown below a_low
        b_idx = None
        for j in range(len(after_a)):
            if float(after_a.iloc[j]['close']) < a_low:
                b_idx = anchor_idx + 1 + j
                break

        t1, t2, t3 = find_profit_targets_bearish(df_anchor, a_low, stop_loss=invalidation)
        risk = invalidation - a_low
        rr = (a_low - t1) / risk if (t1 and risk > 0) else 0.0

        if b_idx is not None:
            # Check Point C: green retest
            c_slice = df_entry.iloc[b_idx + 1:]
            c_idx = None
            risk_dist = max(0.50, a_high - a_low)
            max_b_excursion = a_low - (1.5 * risk_dist)
            if t1 is not None and t1 < a_low:
                max_b_excursion = max(max_b_excursion, float(t1))

            for j in range(len(c_slice)):
                if j > 25:
                    break
                c_row = c_slice.iloc[j]
                if float(c_row['low']) < max_b_excursion:
                    break
                c_high = float(c_row['high'])
                c_close = float(c_row['close'])
                c_open = float(c_row['open'])
                is_green = c_close > c_open
                if (c_high >= a_low and c_close <= a_high and is_green) or \
                   (c_high >= a_high and c_close <= a_high and c_close > float(anchor_candle['open']) and is_green):
                    c_idx = b_idx + 1 + j
                    break

            if c_idx is not None:
                b_row = df_entry.iloc[b_idx]
                c_row = df_entry.iloc[c_idx]
                has_parabolic = bool(swing_meta.get("swing_waves", 0) >= 2 and swing_meta.get("terminal_base", False))
                stage_name = "STAGE_A_PLUS_READY" if has_parabolic else "STAGE_A_READY"
                tier_val = 1 if has_parabolic else 2
                tier_lbl = "TIER_1_GOLD" if has_parabolic else "TIER_2_CORE"
                tier_bdg = "🥇 T1" if has_parabolic else "🥈 T2"
                dist_pct = round(((latest_close - a_low) / latest_close) * 100, 2) if latest_close > 0 else 0.0

                return {
                    "stage": stage_name,
                    "pattern": pattern_label,
                    "anchor_name": anchor_name,
                    "benchmark": a_low,
                    "sl": invalidation,
                    "close": latest_close,
                    "c_high": float(c_row['high']),
                    "dist_to_trigger_pct": dist_pct,
                    "t1": t1, "t2": t2, "t3": t3,
                    "rr": round(rr, 2),
                    "tier": tier_val,
                    "tier_label": tier_lbl,
                    "tier_badge": tier_bdg,
                    "candle_a_time": a_date,
                    "candle_b_time": str(b_row.get("date", "")),
                    "candle_c_time": str(c_row.get("date", "")),
                    "anchor_floor": a_high,
                    "swing_waves": swing_meta.get("swing_waves", 0),
                    "terminal_base": swing_meta.get("terminal_base", False),
                    "direction": "BEAR",
                    "atr_ratio": vcp_metrics.get("atr_ratio", 1.0),
                    "is_squeeze": vcp_metrics.get("is_squeeze", False),
                    "vcp_tier": vcp_metrics.get("vcp_tier", "NORMAL"),
                    "vcp_badge": vcp_metrics.get("vcp_badge", "")
                }

        # Stage B Bearish: Valid Anchor A formed, waiting for B / C
        dist_pct = round(((latest_close - a_low) / latest_close) * 100, 2) if latest_close > 0 else 0.0
        return {
            "stage": "STAGE_B_ANCHOR",
            "pattern": pattern_label,
            "anchor_name": anchor_name,
            "benchmark": a_low,
            "sl": invalidation,
            "close": latest_close,
            "dist_to_trigger_pct": dist_pct,
            "t1": t1, "t2": t2, "t3": t3,
            "rr": round(rr, 2),
            "tier": 3,
            "tier_label": "TIER_3_MOMENTUM",
            "tier_badge": "🌱 B",
            "candle_a_time": a_date,
            "anchor_floor": a_high,
            "swing_waves": swing_meta.get("swing_waves", 0),
            "terminal_base": swing_meta.get("terminal_base", False),
            "direction": "BEAR",
            "atr_ratio": vcp_metrics.get("atr_ratio", 1.0),
            "is_squeeze": vcp_metrics.get("is_squeeze", False),
            "vcp_tier": vcp_metrics.get("vcp_tier", "NORMAL"),
            "vcp_badge": vcp_metrics.get("vcp_badge", "")
        }

    return None


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
    if risk <= 0 or risk < entry_price * 0.002 or ((entry_price - t1) / risk) < 1.5:
        return None

    rr = (entry_price - t1) / risk
    return {
        "Pattern": "TREND_CONT_BEAR",
        "SL": sl_val,
        "T1": t1,
        "T2": t2,
        "T3": t3,
        "Entry": entry_price,
        "Close": entry_price,
        "RR": round(rr, 2),
        "Signal": "Immediate_ReEntry_Bear",
        "CandleTime": str(current_candle.get("date", "")),
        "CandleATime": str(trigger_candle.get("date", "")),
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
        try:
            from patterns_bull import scan_anchor_bcd_breakout as scan_anchor_bcd_breakout_bullanchor, scan_trend_continuation_reentry
        except ImportError:
            from common.patterns_bull import scan_anchor_bcd_breakout as scan_anchor_bcd_breakout_bullanchor, scan_trend_continuation_reentry
        res = scan_anchor_bcd_breakout_bullanchor(df_entry, df_anchor, anchor_tf=anchor_tf, entry_tf=entry_tf)
        if not res:
            res = scan_trend_continuation_reentry(df_entry, df_anchor)
        return res

