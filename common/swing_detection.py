"""
Parabolic Multi-Swing Curve Fitting & Market Structure Detection Module.
Detects cascading parabolic arches (convex/concave polynomial curves) and terminal base absorption
across multi-swing exhaustion structures prior to Anchor/BCD breakouts.
"""
import numpy as np
import pandas as pd
from typing import List, Dict, Tuple, Optional, Any


def is_parabolic_arch_enhanced(
    df_slice: pd.DataFrame, 
    min_r2: float = 0.55,
    allow_skew: bool = True,
    side: str = "BULL"
) -> bool:
    """
    Enhanced parabolic arch/dome detector:
    1. Uses Highs/Closes (BULL dome ∩) or Lows/Closes (BEAR cup ∪) for curvature definition.
    2. Fits 2nd-degree polynomial: y = ax^2 + bx + c.
    3. For BULL (bottom exhaustion dome ∩): a < 0.
       For BEAR (top exhaustion cup ∪): a > 0.
    4. Apex/vertex in middle 15% - 85% range.
    5. Goodness of Fit (R^2) >= min_r2.
    """
    if df_slice is None or len(df_slice) < 6:
        return False
        
    closes = df_slice['close'].values.astype(float)
    highs = df_slice['high'].values.astype(float)
    lows = df_slice['low'].values.astype(float)
    
    is_bull = str(side).upper() == "BULL"
    
    if is_bull:
        # Use Highs + Closes for arch ceiling (dome ∩)
        y = (highs + closes) / 2.0
    else:
        # Use Lows + Closes for arch floor (cup ∪)
        y = (lows + closes) / 2.0
        
    x = np.arange(len(y))
    
    # Fit 2nd-degree polynomial
    try:
        poly_coeffs = np.polyfit(x, y, deg=2)
        a, b, c = poly_coeffs
    except Exception:
        return False
    
    # 1. Curvature direction check
    if is_bull:
        # Must be concave down dome (a < 0)
        if a >= 0:
            return False
    else:
        # Must be concave up cup (a > 0)
        if a <= 0:
            return False
        
    # 2. Apex (vertex) inside middle 15% - 85% range
    if abs(a) < 1e-12:
        return False
    vertex_x = -b / (2.0 * a)
    if not (0.15 * len(y) <= vertex_x <= 0.85 * len(y)):
        return False
        
    # 3. Goodness of Fit (R^2)
    y_pred = np.polyval(poly_coeffs, x)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    ss_res = np.sum((y - y_pred) ** 2)
    r2 = 1.0 - (ss_res / (ss_tot + 1e-8))
    
    return float(r2) >= min_r2


def extract_swing_pivots(
    df: pd.DataFrame, 
    min_candles_per_leg: int = 3,
    side: str = "BULL",
    min_atr_factor: float = 0.6
) -> List[int]:
    """
    Extracts local extrema indices for swing waves with ATR prominence filtering,
    ignoring dead zero-volume flatline candles and micro-ripples.
    For BULL: extracts distinct swing low indices L1, L2, L3, ...
    For BEAR: extracts distinct swing high indices H1, H2, H3, ...
    """
    if df is None or len(df) < (min_candles_per_leg * 2 + 1):
        return []
        
    highs = df['high'].values.astype(float)
    lows = df['low'].values.astype(float)
    volumes = df['volume'].values.astype(float) if 'volume' in df.columns else np.ones(len(df))
    n = len(df)
    
    # Calculate dataset-wide ATR for swing prominence threshold
    candle_ranges = np.abs(highs - lows)
    mean_atr = float(np.nanmean(candle_ranges)) if len(candle_ranges) > 0 else 1.0
    if np.isnan(mean_atr) or mean_atr <= 0:
        mean_atr = float(np.nanmean(lows) * 0.02) if len(lows) > 0 else 1.0
    min_displacement = max(mean_atr * min_atr_factor, float(np.nanmean(lows) * 0.01) if len(lows) > 0 else 0.5)

    is_bull = str(side).upper() == "BULL"
    swing_indices = []
    
    for i in range(min_candles_per_leg, n - min_candles_per_leg):
        # Ignore dead flatline quotation bars (0 volume and high == low)
        if volumes[i] == 0 and highs[i] == lows[i]:
            continue

        if is_bull:
            window = lows[i - min_candles_per_leg : i + min_candles_per_leg + 1]
            if lows[i] == np.min(window):
                # Ensure the pivot has distinct price displacement from previous pivot or swing high in between
                if not swing_indices:
                    swing_indices.append(i)
                elif (i - swing_indices[-1] >= min_candles_per_leg):
                    inter_high = np.max(highs[swing_indices[-1] : i + 1])
                    if (inter_high - lows[i] >= min_displacement) or abs(lows[i] - lows[swing_indices[-1]]) >= min_displacement:
                        swing_indices.append(i)
                    elif lows[i] < lows[swing_indices[-1]]:
                        swing_indices[-1] = i
                elif lows[i] < lows[swing_indices[-1]]:
                    swing_indices[-1] = i
        else:
            window = highs[i - min_candles_per_leg : i + min_candles_per_leg + 1]
            if highs[i] == np.max(window):
                if not swing_indices:
                    swing_indices.append(i)
                elif (i - swing_indices[-1] >= min_candles_per_leg):
                    inter_low = np.min(lows[swing_indices[-1] : i + 1])
                    if (highs[i] - inter_low >= min_displacement) or abs(highs[i] - highs[swing_indices[-1]]) >= min_displacement:
                        swing_indices.append(i)
                    elif highs[i] > highs[swing_indices[-1]]:
                        swing_indices[-1] = i
                elif highs[i] > highs[swing_indices[-1]]:
                    swing_indices[-1] = i
                    
    return swing_indices


def validate_parabolic_cascade_structure(
    df: pd.DataFrame, 
    swing_indices: List[int],
    min_cascading_waves: int = 3,
    side: str = "BULL",
    min_r2: float = 0.55
) -> Dict[str, Any]:
    """
    Validates full market structure:
    - Cascading Parabolic Arches (Lower Highs + Lower Lows for BULL; Higher Highs + Higher Lows for BEAR)
    - Terminal Base / Support Absorption detection (Point 4)
    """
    if len(swing_indices) < 2:
        return {"valid": False, "reason": "Insufficient swing points", "details": []}

    is_bull = str(side).upper() == "BULL"
    valid_arches = 0
    wave_details = []
    
    for i in range(len(swing_indices) - 1):
        start_idx = swing_indices[i]
        end_idx = swing_indices[i + 1]
        
        df_wave = df.iloc[start_idx : end_idx + 1]
        
        # Test parabolic curvature
        is_arch = is_parabolic_arch_enhanced(df_wave, min_r2=min_r2, side=side)
        
        if is_bull:
            start_val = float(df['low'].iloc[start_idx])
            end_val = float(df['low'].iloc[end_idx])
            is_monotonic = end_val < start_val  # 2nd leg low is breaking 1st leg low
            # Structural BOS: Wave price must have a confirmed candle close below the prior structural low
            has_bos = bool((df_wave['close'] < start_val).any()) if not df_wave.empty else False
            wave_extrema = float(df_wave['high'].max())  # Peak
        else:
            start_val = float(df['high'].iloc[start_idx])
            end_val = float(df['high'].iloc[end_idx])
            is_monotonic = end_val > start_val  # 2nd leg high is breaking 1st leg high
            # Structural BOS: Wave price must have a confirmed candle close above the prior structural high
            has_bos = bool((df_wave['close'] > start_val).any()) if not df_wave.empty else False
            wave_extrema = float(df_wave['low'].min())  # Trough
        
        wave_details.append({
            "wave_index": i + 1,
            "is_arch": is_arch,
            "is_monotonic": is_monotonic,
            "has_bos": has_bos,
            "extrema": wave_extrema,
            "base_val": end_val
        })
        
        if is_arch and is_monotonic:
            valid_arches += 1

    if not wave_details:
        return {"valid": False, "reason": "No waves constructed", "details": []}

    # Macro trend check: Progressive cascade (Lower Highs for Bull; Higher Lows for Bear)
    extremas = [w["extrema"] for w in wave_details]
    if is_bull:
        cascade_progression = all(extremas[i] > extremas[i+1] for i in range(len(extremas)-1)) if len(extremas) > 1 else True
    else:
        cascade_progression = all(extremas[i] < extremas[i+1] for i in range(len(extremas)-1)) if len(extremas) > 1 else True

    # Check structural BOS integrity across all cascading waves
    all_bos_confirmed = all(w.get("has_bos", False) for w in wave_details[:-1]) if len(wave_details) > 1 else True

    # Detect terminal consolidation / base (Point 4 handling / 3rd swing bottom)
    last_wave = wave_details[-1]
    has_terminal_base = False
    if len(wave_details) >= 2:
        prev_base = wave_details[-2]["base_val"]
        last_base = last_wave["base_val"]
        if last_base > 0:
            pct_diff = abs(last_base - prev_base) / last_base
            has_terminal_base = (not last_wave["is_arch"]) and (pct_diff < 0.02)

    is_full_pattern_valid = (
        valid_arches >= min_cascading_waves and 
        cascade_progression and 
        (last_wave["is_arch"] or has_terminal_base)
    )

    # Multi-Tier Soft Classification
    # Tier 1 (Gold): >=3 waves with confirmed BOS + cascade progression + terminal 3rd swing bottom/base
    # Tier 2 (Core): >=2 waves (or 2-wave arch) + cascade progression
    # Tier 3 (Momentum): 1-wave or structural re-entry
    if valid_arches >= 3 and cascade_progression and all_bos_confirmed and (last_wave["is_arch"] or has_terminal_base):
        tier = 1
        tier_label = "TIER_1_GOLD"
        tier_badge = "🥇 T1"
    elif valid_arches >= 2 and cascade_progression:
        tier = 2
        tier_label = "TIER_2_CORE"
        tier_badge = "🥈 T2"
    else:
        tier = 3
        tier_label = "TIER_3_MOMENTUM"
        tier_badge = "🥉 T3"

    return {
        "valid": is_full_pattern_valid,
        "valid_arch_count": valid_arches,
        "cascade_progression": cascade_progression,
        "has_terminal_base": has_terminal_base,
        "all_bos_confirmed": all_bos_confirmed,
        "tier": tier,
        "tier_label": tier_label,
        "tier_badge": tier_badge,
        "details": wave_details
    }


def detect_parabolic_multi_swings(
    df: pd.DataFrame,
    side: str = "BULL",
    min_swings: int = 3,
    min_candles_per_leg: int = 3,
    min_r2: float = 0.50,
    max_bars_after_terminal: int = 45
) -> Dict[str, Any]:
    """
    Complete end-to-end multi-swing parabolic cascade detector with Multi-Tier Scoring.
    Evaluates:
    - Tier 1 (Gold): >= 3 Parabolic Waves (R^2 >= 0.55) with Terminal Absorption Base.
    - Tier 2 (Core): >= 2 Parabolic Waves (R^2 >= 0.50) (e.g. Double Bottom / Liquidity Sweep).
    - Tier 3 (Momentum): Trend Continuation / Structural Re-entry.
    """
    if df is None or len(df) < (2 * min_candles_per_leg * 2):
        return {"matched": False, "reason": "Insufficient candles", "valid": False, "tier": 3, "tier_label": "TIER_3_MOMENTUM", "tier_badge": "🥉 T3"}

    # Strip leading dead zero-volume flatline bars from illiquid option history
    if 'volume' in df.columns:
        valid_mask = (df['volume'] > 0) | (df['high'] != df['low'])
        if valid_mask.sum() >= (2 * min_candles_per_leg * 2):
            first_valid_idx = valid_mask.idxmax()
            if isinstance(first_valid_idx, int) and first_valid_idx > 0:
                df = df.iloc[first_valid_idx:].reset_index(drop=True)
        
    pivots = extract_swing_pivots(df, min_candles_per_leg=min_candles_per_leg, side=side)
    if len(pivots) < 3:
        # Fallback to lighter 2-candle pivot order to detect tighter 2-wave structures
        pivots_light = extract_swing_pivots(df, min_candles_per_leg=2, side=side)
        if len(pivots_light) >= 3:
            pivots = pivots_light
        else:
            return {
                "matched": False, 
                "reason": f"Insufficient swing pivots ({len(pivots)} found, need >= 3)", 
                "valid": False,
                "tier": 3,
                "tier_label": "TIER_3_MOMENTUM",
                "tier_badge": "🥉 T3",
                "valid_arch_count": 0,
                "has_terminal_base": False
            }

    # Recency check: terminal swing must not be excessively old
    terminal_idx = pivots[-1]
    bars_since_terminal = len(df) - 1 - terminal_idx
    if max_bars_after_terminal > 0 and bars_since_terminal > max_bars_after_terminal:
        return {
            "matched": False,
            "reason": f"Terminal swing is too old ({bars_since_terminal} bars ago, max allowed: {max_bars_after_terminal})",
            "valid": False,
            "tier": 3,
            "tier_label": "TIER_3_MOMENTUM",
            "tier_badge": "🥉 T3",
            "valid_arch_count": 0,
            "has_terminal_base": False
        }
        
    res = validate_parabolic_cascade_structure(
        df, 
        swing_indices=pivots, 
        min_cascading_waves=min_swings, 
        side=side, 
        min_r2=min_r2
    )
    
    # Matched if Tier 1 or Tier 2 (>= 2 valid cascading arches)
    res["matched"] = res["valid"] or (res.get("valid_arch_count", 0) >= 2)
    res["swing_indices"] = pivots
    res["terminal_swing_idx"] = terminal_idx
    res["bars_since_terminal"] = bars_since_terminal
    if 'date' in df.columns and len(df) > terminal_idx:
        res["terminal_swing_date"] = str(df['date'].iloc[terminal_idx])
    return res
