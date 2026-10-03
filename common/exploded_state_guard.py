"""
common/exploded_state_guard.py
==============================
Anti-Exploded State & Point-of-Execution Chase Protection Guard.

Protects automated trading engines (Stock Options, Index Options, Cash Equities)
and manual 1-Click execution from entering trades after an option or underlying asset
has already exploded in price due to scanner intervals, quote latency, or rapid market surges.

Core Rules & Mathematical Invariants:
1. Target Reach / Near-T1 Exhaustion:
   - Live Price >= T1 Target -> HARD REJECT (Move already completed).
   - Live Price >= 85% of T1 distance -> HARD REJECT (Near-target exhaustion / climax trap).
2. Target Distance Consumed Ratio:
   - If (Live Price - Benchmark) / (T1 - Benchmark) > max_target_consumed_pct (default 0.20 / 20%),
     reject trade. Entering after >20% of the target is consumed severely impairs R:R.
3. Max Benchmark Chase Ceiling:
   - Options: Maximum +8.0% above breakout trigger benchmark.
   - Equities: Maximum +1.5% above breakout trigger benchmark.
4. Live Risk-to-Reward Inversion Protection:
   - Computes live R:R = (T1 - Live Price) / (Live Price - Stop Loss).
   - If live R:R drops below 1.00 at the moment of execution, reject (negative mathematical expectancy).
5. Underlying Spot Climax Protection:
   - If Spot has already touched Spot T1 or consumed > 30% of its target distance, reject option entry.
"""

import logging
from typing import Tuple, Dict, Any, Optional


def is_option_contract(contract_str: str) -> bool:
    """Check if symbol represents an option contract."""
    if not contract_str:
        return False
    c = str(contract_str).strip().upper()
    if ":" in c:
        c = c.split(":")[-1]
    return (c.endswith("CE") or c.endswith("PE")) and any(ch.isdigit() for ch in c)


def check_exploded_state_guard(
    live_price: float,
    benchmark_price: float,
    t1_target: float,
    stop_loss: float = 0.0,
    symbol: str = "",
    contract: str = "",
    is_option: Optional[bool] = None,
    spot_ltp: Optional[float] = None,
    spot_trigger: Optional[float] = None,
    spot_t1: Optional[float] = None,
    max_chase_pct: Optional[float] = None,
    max_target_consumed_pct: float = 0.20,
    min_live_rr: float = 1.00
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Evaluates whether an asset is in an 'exploded state' right before order placement.

    Args:
        live_price: Fresh live quote price (Best Ask or LTP) right at execution.
        benchmark_price: Original breakout trigger / anchor benchmark price.
        t1_target: Target 1 price.
        stop_loss: Stop Loss price (used to calculate live R:R).
        symbol: Underlying symbol name.
        contract: Trading symbol or contract name.
        is_option: Explicit flag (auto-detected if None).
        spot_ltp: Current underlying spot price (optional).
        spot_trigger: Spot Point D breakout trigger price (optional).
        spot_t1: Spot Target 1 price (optional).
        max_chase_pct: Max allowed % increase above benchmark (default: 8% for options, 1.5% for stocks).
        max_target_consumed_pct: Max fraction of target move already consumed (default: 0.20 = 20%).
        min_live_rr: Minimum acceptable live R:R at execution (default: 1.00).

    Returns:
        tuple: (is_safe_to_enter: bool, reason: str, metrics: dict)
    """
    target_ident = contract or symbol or "UNKNOWN"
    opt_flag = is_option if is_option is not None else is_option_contract(contract or symbol)

    if max_chase_pct is None:
        max_chase_pct = 0.08 if opt_flag else 0.015

    live_p = float(live_price or 0.0)
    bm_p = float(benchmark_price or 0.0)
    t1_p = float(t1_target or 0.0)
    sl_p = float(stop_loss or 0.0)

    metrics = {
        "contract": target_ident,
        "live_price": live_p,
        "benchmark": bm_p,
        "t1": t1_p,
        "sl": sl_p,
        "is_option": opt_flag,
        "consumed_pct": 0.0,
        "chase_pct": 0.0,
        "live_rr": 0.0
    }

    if live_p <= 0:
        return False, f"INVALID_LIVE_PRICE: Live price for {target_ident} is <= 0 ({live_p})", metrics

    # If benchmark or T1 is missing, apply basic sanity check against live price
    if bm_p <= 0 or t1_p <= 0:
        return True, "BYPASS_INCOMPLETE_TARGETS", metrics

    # Direction check: we assume Long / Bull Call / Bear Put buying where target > benchmark
    is_upward_target = t1_p > bm_p

    if is_upward_target:
        # ── 1. Target Already Reached or Exceeded ──
        if live_p >= t1_p:
            msg = f"🛡️ [ANTI_EXPLOSION] {target_ident}: TARGET 1 ALREADY HIT! Live ₹{live_p:.2f} >= T1 ₹{t1_p:.2f} (BM ₹{bm_p:.2f}). Late entry strictly blocked."
            metrics["consumed_pct"] = 100.0
            return False, msg, metrics

        # ── 2. Near-Target Exhaustion (Within 15% of T1) ──
        target_span = t1_p - bm_p
        near_t1_ceiling = bm_p + (0.85 * target_span)
        if live_p >= near_t1_ceiling:
            msg = f"🛡️ [ANTI_EXPLOSION] {target_ident}: NEAR-TARGET CLIMAX! Live ₹{live_p:.2f} is within 15% of T1 ₹{t1_p:.2f} (Ceiling ₹{near_t1_ceiling:.2f}). Entry blocked."
            metrics["consumed_pct"] = round(((live_p - bm_p) / target_span) * 100, 1)
            return False, msg, metrics

        # ── 3. Target Distance Consumed Guard (> 20% by default) ──
        consumed_dist = live_p - bm_p
        consumed_ratio = consumed_dist / target_span
        metrics["consumed_pct"] = round(consumed_ratio * 100, 1)

        if consumed_ratio > max_target_consumed_pct:
            max_allowed_price = round(bm_p + (max_target_consumed_pct * target_span), 2)
            msg = (
                f"🛡️ [ANTI_EXPLOSION] {target_ident}: MOVE ALREADY EXPLODED! Live ₹{live_p:.2f} has consumed "
                f"{consumed_ratio * 100:.1f}% of T1 distance (Max allowed: {max_target_consumed_pct * 100:.0f}%, "
                f"Max Price: ₹{max_allowed_price:.2f}, BM: ₹{bm_p:.2f}, T1: ₹{t1_p:.2f}). Holding candidate for retest."
            )
            return False, msg, metrics

        # ── 4. Max Percentage Runaway from Benchmark ──
        chase_pct = (live_p - bm_p) / bm_p
        metrics["chase_pct"] = round(chase_pct * 100, 2)
        if chase_pct > max_chase_pct:
            max_pct_price = round(bm_p * (1.0 + max_chase_pct), 2)
            msg = (
                f"🛡️ [ANTI_EXPLOSION] {target_ident}: MAX CHASE EXCEEDED! Live ₹{live_p:.2f} is +{chase_pct * 100:.1f}% "
                f"above Benchmark ₹{bm_p:.2f} (Max allowed: +{max_chase_pct * 100:.1f}%, Max Price: ₹{max_pct_price:.2f})."
            )
            return False, msg, metrics

        # ── 5. Live Risk-to-Reward Inversion Protection ──
        if sl_p > 0 and live_p > sl_p:
            live_risk = live_p - sl_p
            live_reward = t1_p - live_p
            if live_risk > 0:
                live_rr = live_reward / live_risk
                metrics["live_rr"] = round(live_rr, 2)
                if live_rr < min_live_rr:
                    msg = (
                        f"🛡️ [ANTI_EXPLOSION] {target_ident}: INVERTED LIVE R:R! At Live ₹{live_p:.2f}, Live R:R is {live_rr:.2f} "
                        f"(< {min_live_rr:.2f} minimum required; Risk=₹{live_risk:.2f}, Remaining Reward=₹{live_reward:.2f})."
                    )
                    return False, msg, metrics

    else:
        # Downward target (Cash Equity Short / MIS) where target < benchmark
        if live_p <= t1_p:
            msg = f"🛡️ [ANTI_EXPLOSION] {target_ident}: SHORT TARGET 1 ALREADY HIT! Live ₹{live_p:.2f} <= T1 ₹{t1_p:.2f}. Late short blocked."
            return False, msg, metrics

        target_span = bm_p - t1_p
        consumed_dist = bm_p - live_p
        consumed_ratio = consumed_dist / target_span if target_span > 0 else 0.0
        metrics["consumed_pct"] = round(consumed_ratio * 100, 1)

        if consumed_ratio > max_target_consumed_pct:
            msg = f"🛡️ [ANTI_EXPLOSION] {target_ident}: SHORT MOVE EXPLODED! Live ₹{live_p:.2f} has consumed {consumed_ratio*100:.1f}% of short target."
            return False, msg, metrics

    # ── 6. Underlying Spot Climax Protection (if spot data provided) ──
    if spot_ltp is not None and spot_trigger is not None and spot_t1 is not None:
        s_live = float(spot_ltp)
        s_trig = float(spot_trigger)
        s_t1 = float(spot_t1)
        if s_t1 > s_trig and s_trig > 0:
            if s_live >= s_t1:
                msg = f"🛡️ [ANTI_EXPLOSION] {target_ident}: UNDERLYING SPOT CLIMAX! Spot ₹{s_live:.2f} >= Spot T1 ₹{s_t1:.2f}. Option entry blocked."
                return False, msg, metrics
            s_span = s_t1 - s_trig
            s_consumed = (s_live - s_trig) / s_span
            if s_consumed > 0.35:
                msg = f"🛡️ [ANTI_EXPLOSION] {target_ident}: UNDERLYING SPOT OVEREXTENDED! Spot has consumed {s_consumed*100:.1f}% of target distance (> 35%)."
                return False, msg, metrics

    return True, "SAFE_EXECUTION_STATE", metrics
