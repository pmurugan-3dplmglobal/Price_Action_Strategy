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
    side: str = "BULL"
) -> List[int]:
    """
    Extracts local extrema indices for swing waves.
    For BULL: extracts swing low indices L1, L2, L3, ...
    For BEAR: extracts swing high indices H1, H2, H3, ...
    """
    if df is None or len(df) < (min_candles_per_leg * 2 + 1):
        return []
        
    highs = df['high'].values.astype(float)
    lows = df['low'].values.astype(float)
    n = len(df)
    
    is_bull = str(side).upper() == "BULL"
    swing_indices = []
    
    for i in range(min_candles_per_leg, n - min_candles_per_leg):
        if is_bull:
            window = lows[i - min_candles_per_leg : i + min_candles_per_leg + 1]
            if lows[i] == np.min(window):
                if not swing_indices or (i - swing_indices[-1] >= min_candles_per_leg):
                    swing_indices.append(i)
                elif lows[i] < lows[swing_indices[-1]]:
                    swing_indices[-1] = i
        else:
            window = highs[i - min_candles_per_leg : i + min_candles_per_leg + 1]
            if highs[i] == np.max(window):
                if not swing_indices or (i - swing_indices[-1] >= min_candles_per_leg):
                    swing_indices.append(i)
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
            is_monotonic = end_val < start_val  # Lower Low
            wave_extrema = float(df_wave['high'].max())  # Peak
        else:
            start_val = float(df['high'].iloc[start_idx])
            end_val = float(df['high'].iloc[end_idx])
            is_monotonic = end_val > start_val  # Higher High
            wave_extrema = float(df_wave['low'].min())  # Trough
        
        wave_details.append({
            "wave_index": i + 1,
            "is_arch": is_arch,
            "is_monotonic": is_monotonic,
            "extrema": wave_extrema,
            "base_val": end_val
        })
        
        if is_arch and is_monotonic:
            valid_arches += 1

    if not wave_details:
        return {"valid": False, "reason": "No waves constructed", "details": []}

    # Macro trend check: Progressive cascade
    extremas = [w["extrema"] for w in wave_details]
    if is_bull:
        cascade_progression = all(extremas[i] > extremas[i+1] for i in range(len(extremas)-1)) if len(extremas) > 1 else True
    else:
        cascade_progression = all(extremas[i] < extremas[i+1] for i in range(len(extremas)-1)) if len(extremas) > 1 else True

    # Detect terminal consolidation / base (Point 4 handling)
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

    return {
        "valid": is_full_pattern_valid,
        "valid_arch_count": valid_arches,
        "cascade_progression": cascade_progression,
        "has_terminal_base": has_terminal_base,
        "details": wave_details
    }


def detect_parabolic_multi_swings(
    df: pd.DataFrame,
    side: str = "BULL",
    min_swings: int = 3,
    min_candles_per_leg: int = 3,
    min_r2: float = 0.55,
    max_bars_after_terminal: int = 15
) -> Dict[str, Any]:
    """
    Complete end-to-end multi-swing parabolic cascade detector.
    Enforces that:
    1. Alternating swing waves form valid parabolic arches with cascade progression.
    2. The terminal swing (e.g. 4th swing base) was formed RECENTLY (within max_bars_after_terminal).
    """
    if df is None or len(df) < (min_swings * min_candles_per_leg * 2):
        return {"matched": False, "reason": "Insufficient candles", "valid": False}
        
    pivots = extract_swing_pivots(df, min_candles_per_leg=min_candles_per_leg, side=side)
    if len(pivots) < (min_swings + 1):
        return {"matched": False, "reason": f"Insufficient swing pivots ({len(pivots)} found, need {min_swings + 1})", "valid": False}

    # Recency check: terminal swing must not be too old
    terminal_idx = pivots[-1]
    bars_since_terminal = len(df) - 1 - terminal_idx
    if max_bars_after_terminal > 0 and bars_since_terminal > max_bars_after_terminal:
        return {
            "matched": False,
            "reason": f"Terminal swing is too old ({bars_since_terminal} bars ago, max allowed: {max_bars_after_terminal})",
            "valid": False
        }
        
    res = validate_parabolic_cascade_structure(
        df, 
        swing_indices=pivots, 
        min_cascading_waves=min_swings, 
        side=side, 
        min_r2=min_r2
    )
    
    res["matched"] = res["valid"]
    res["swing_indices"] = pivots
    res["terminal_swing_idx"] = terminal_idx
    res["bars_since_terminal"] = bars_since_terminal
    if 'date' in df.columns and len(df) > terminal_idx:
        res["terminal_swing_date"] = str(df['date'].iloc[terminal_idx])
    return res
