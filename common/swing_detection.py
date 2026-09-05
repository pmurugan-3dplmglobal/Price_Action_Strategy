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
        
    x = np.arange(int(len(y)), dtype=float)
    
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


def get_adaptive_leg_length(
    df: Optional[pd.DataFrame] = None, 
    symbol: str = "", 
    timeframe_str: str = "30minute", 
    default_leg: int = 3
) -> int:
    """
    Calculates the optimal min_candles_per_leg for swing pivot extraction via a 3-tier hierarchy:
    1. Explicit symbol override in input/program_config.json.
    2. Dynamic ATR Volatility-Adaptive calculation (scaled between min_leg and max_leg).
    3. Global default (fallback).
    """
    import json, os
    try:
        import paths
        cfg_path = paths.PROGRAM_CONFIG_FILE
    except Exception:
        cfg_path = "input/program_config.json"

    overrides = {}
    use_vol = True
    min_bound = 2
    max_bound = 5

    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                c = json.load(f)
            s_cfg = c.get("swing_leg_config", {})
            overrides = s_cfg.get("overrides", {})
            default_leg = int(s_cfg.get("default", default_leg))
            use_vol = bool(s_cfg.get("volatility_adaptive", True))
            min_bound = int(s_cfg.get("min_leg", 2))
            max_bound = int(s_cfg.get("max_leg", 5))
        except Exception:
            pass

    # Tier 1: Explicit symbol override
    sym_clean = str(symbol).upper().strip()
    for k, v in overrides.items():
        if k.upper() in sym_clean:
            return int(v)

    # Tier 2: Dynamic ATR Volatility Adaptation
    if use_vol and df is not None and len(df) >= 14:
        try:
            highs = df['high'].values.astype(float)
            lows = df['low'].values.astype(float)
            closes = df['close'].values.astype(float)
            tr = np.maximum(highs - lows, np.maximum(np.abs(highs - np.roll(closes, 1)), np.abs(lows - np.roll(closes, 1))))
            atr = float(np.nanmean(tr[-14:]))
            curr_price = float(closes[-1])
            if curr_price > 0 and atr > 0:
                vol_pct = (atr / curr_price) * 100.0
                is_daily = 'day' in str(timeframe_str).lower() or '1d' in str(timeframe_str).lower()
                if is_daily:
                    if vol_pct < 1.5: leg = min_bound
                    elif vol_pct > 3.2: leg = max_bound
                    elif vol_pct > 2.2: leg = min(4, max_bound)
                    elif vol_pct > 1.6: leg = 3
                    else: leg = min_bound
                else:
                    if vol_pct < 0.40: leg = min_bound
                    elif vol_pct > 1.20: leg = max_bound
                    elif vol_pct > 0.80: leg = min(4, max_bound)
                    elif vol_pct > 0.50: leg = 3
                    else: leg = min_bound
                return leg
        except Exception:
            pass

    return default_leg


def detect_parabolic_multi_swings(
    df: pd.DataFrame,
    side: str = "BULL",
    min_swings: int = 3,
    min_candles_per_leg: Optional[int] = None,
    min_r2: float = 0.50,
    max_bars_after_terminal: int = 45,
    symbol: str = "",
    timeframe_str: str = "30minute"
) -> Dict[str, Any]:
    """
    Complete end-to-end multi-swing parabolic cascade detector with Multi-Tier Scoring.
    Evaluates:
    - Tier 1 (Gold): >= 3 Parabolic Waves (R^2 >= 0.55) with Terminal Absorption Base.
    - Tier 2 (Core): >= 2 Parabolic Waves (R^2 >= 0.50) (e.g. Double Bottom / Liquidity Sweep).
    - Tier 3 (Momentum): Trend Continuation / Structural Re-entry.
    """
    if min_candles_per_leg is None or min_candles_per_leg <= 0:
        min_candles_per_leg = get_adaptive_leg_length(df, symbol=symbol, timeframe_str=timeframe_str)

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


def calculate_vcp_metrics(df: Optional[pd.DataFrame]) -> Dict[str, Any]:
    """
    Calculates Volatility Contraction Pattern (VCP) metrics:
    1. Contraction Ratio: ATR(3) / ATR(14)
       - When ATR(3) / ATR(14) <= 0.60, volatility has compressed >= 40% vs recent baseline.
    2. TTM Squeeze: Bollinger Bands (20, 2.0 std) strictly inside Keltner Channels (20, 1.5 ATR20).
    3. Returns classification: 'ULTRA_SQUEEZE' | 'SQUEEZE' | 'VCP_COILED' | 'NORMAL' and formatted display badge.
    """
    default_res = {
        "atr_ratio": 1.0,
        "is_squeeze": False,
        "vcp_tier": "NORMAL",
        "vcp_badge": "",
        "atr3": 0.0,
        "atr14": 0.0
    }
    if df is None or len(df) < 20:
        return default_res

    try:
        high = df['high'].values.astype(float)
        low = df['low'].values.astype(float)
        close = df['close'].values.astype(float)
        n = len(df)
        if n < 20:
            return default_res

        # True Range calculation
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0]
        tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))

        # ATR 14 and ATR 3
        atr14 = float(np.mean(tr[-14:])) if n >= 14 else float(np.mean(tr))
        atr3 = float(np.mean(tr[-3:])) if n >= 3 else float(np.mean(tr))
        atr_ratio = round(atr3 / atr14, 2) if atr14 > 1e-6 else 1.0

        # Bollinger Bands (20 period, 2.0 std dev)
        slice_close_20 = close[-20:]
        sma20 = float(np.mean(slice_close_20))
        std20 = float(np.std(slice_close_20))
        bb_upper = sma20 + (2.0 * std20)
        bb_lower = sma20 - (2.0 * std20)

        # Keltner Channels (20 period EMA + 1.5 * ATR20)
        alpha = 2.0 / (20.0 + 1.0)
        ema20 = float(slice_close_20[0])
        for val in slice_close_20[1:]:
            ema20 = alpha * float(val) + (1.0 - alpha) * ema20

        atr20 = float(np.mean(tr[-20:]))
        kc_upper = ema20 + (1.5 * atr20)
        kc_lower = ema20 - (1.5 * atr20)

        # Squeeze condition: Bollinger Bands strictly inside Keltner Channel
        is_squeeze = bool(bb_upper < kc_upper and bb_lower > kc_lower)

        if is_squeeze and atr_ratio <= 0.60:
            vcp_tier = "ULTRA_SQUEEZE"
            vcp_badge = f"🔥 ULTRA SQZ {atr_ratio:.2f}"
        elif is_squeeze:
            vcp_tier = "SQUEEZE"
            vcp_badge = f"🔥 SQZ {atr_ratio:.2f}"
        elif atr_ratio <= 0.60:
            vcp_tier = "VCP_COILED"
            vcp_badge = f"⚡ VCP {atr_ratio:.2f}"
        else:
            vcp_tier = "NORMAL"
            vcp_badge = ""

        return {
            "atr_ratio": atr_ratio,
            "is_squeeze": is_squeeze,
            "vcp_tier": vcp_tier,
            "vcp_badge": vcp_badge,
            "atr3": round(atr3, 2),
            "atr14": round(atr14, 2)
        }
    except Exception:
        return default_res


def calculate_option_vwap(df_opt: Optional[pd.DataFrame]) -> Dict[str, Any]:
    """
    Calculates intraday Volume Weighted Average Price (VWAP) and Volume-Weighted
    Standard Deviation (+2σ bands) for an option contract.
    Returns:
      vwap: float (intraday VWAP)
      vwap_std: float (volume-weighted standard deviation)
      vwap_zscore: float (number of standard deviations from VWAP)
      vwap_upper_2sigma: float (VWAP + 2*sigma threshold)
      vwap_lower_2sigma: float (VWAP - 2*sigma threshold)
      stretch_pct: float (percentage stretch of latest close above/below VWAP)
      is_overstretched: bool (True if z_score > 2.0 or stretch_pct > 15%)
      vwap_status: 'FAIR' (<= +1.0σ and <=8%), 'EXPANDED' (+1.0σ to +2.0σ or 8-15%), 'STRETCHED' (> +2.0σ or >15%)
    """
    default_res = {
        "vwap": 0.0,
        "vwap_std": 0.0,
        "vwap_zscore": 0.0,
        "vwap_upper_2sigma": 0.0,
        "vwap_lower_2sigma": 0.0,
        "stretch_pct": 0.0,
        "is_overstretched": False,
        "vwap_status": "FAIR"
    }
    if df_opt is None or df_opt.empty or 'volume' not in df_opt.columns or 'close' not in df_opt.columns:
        return default_res
    try:
        last_date = str(df_opt.iloc[-1]['date'])[:10]
        # Intraday filter: only today's session candles
        df_today = df_opt[df_opt['date'].astype(str).str.startswith(last_date)]
        if df_today.empty or len(df_today) < 1:
            df_today = df_opt

        vol = df_today['volume'].values.astype(float)
        close = df_today['close'].values.astype(float)
        high = df_today['high'].values.astype(float) if 'high' in df_today.columns else close
        low = df_today['low'].values.astype(float) if 'low' in df_today.columns else close
        typical_price = (high + low + close) / 3.0

        sum_vol = np.sum(vol)
        ltp = float(close[-1])
        if sum_vol <= 0:
            return {
                "vwap": ltp,
                "vwap_std": 0.0,
                "vwap_zscore": 0.0,
                "vwap_upper_2sigma": ltp,
                "vwap_lower_2sigma": ltp,
                "stretch_pct": 0.0,
                "is_overstretched": False,
                "vwap_status": "FAIR"
            }

        vwap = float(np.sum(typical_price * vol) / sum_vol)
        vw_variance = float(np.sum(vol * ((typical_price - vwap) ** 2)) / sum_vol)
        vwap_std = float(np.sqrt(max(0.0, vw_variance)))
        vwap_upper_2sigma = round(vwap + (2.0 * vwap_std), 2)
        vwap_lower_2sigma = round(max(0.0, vwap - (2.0 * vwap_std)), 2)

        stretch_pct = round(((ltp - vwap) / vwap) * 100.0, 2) if vwap > 0 else 0.0
        z_score = round((ltp - vwap) / vwap_std, 2) if vwap_std > 0.01 else 0.0

        if z_score > 2.0 or stretch_pct > 15.0:
            status = "STRETCHED"
            is_over = True
        elif z_score <= 1.0 and stretch_pct <= 8.0:
            status = "FAIR"
            is_over = False
        else:
            status = "EXPANDED"
            is_over = False

        return {
            "vwap": round(vwap, 2),
            "vwap_std": round(vwap_std, 2),
            "vwap_zscore": z_score,
            "vwap_upper_2sigma": vwap_upper_2sigma,
            "vwap_lower_2sigma": vwap_lower_2sigma,
            "stretch_pct": stretch_pct,
            "is_overstretched": is_over,
            "vwap_status": status
        }
    except Exception:
        return default_res


def calculate_twap_c_stability(c_window: Optional[pd.DataFrame], risk_dist: float = 1.0) -> Dict[str, Any]:
    """
    Evaluates Point C absorption base stability via Time-Weighted Average Price (TWAP) standard deviation.
    When an institution quietly accumulates using TWAP, price stabilizes with minimal standard deviation.
    Returns:
      twap: float
      twap_std: float
      twap_stable: bool (True if twap_std <= 0.25 * risk_dist)
      twap_score: float (0.0 to 1.0)
    """
    default_res = {
        "twap": 0.0,
        "twap_std": 0.0,
        "twap_stable": False,
        "twap_score": 0.0
    }
    if c_window is None or len(c_window) < 2 or 'close' not in c_window.columns:
        return default_res
    try:
        c_closes = c_window['close'].values.astype(float)
        twap_val = float(np.mean(c_closes))
        twap_std = float(np.std(c_closes))
        effective_risk = max(0.50, float(risk_dist))
        twap_c_ratio = twap_std / effective_risk
        twap_stable = bool(twap_c_ratio <= 0.25)
        twap_score = round(max(0.0, 1.0 - min(1.0, twap_c_ratio)), 2)
        return {
            "twap": round(twap_val, 2),
            "twap_std": round(twap_std, 2),
            "twap_stable": twap_stable,
            "twap_score": twap_score
        }
    except Exception:
        return default_res
