"""
vix_guard.py — India VIX Macro Regime Guard.

Monitors India VIX (NSE:INDIA VIX / token 264969) to govern trade entries:
- Extreme Regime (VIX > 25.0): Circuit-risk/event volatility — all new trade entries are blocked.
- Elevated Regime (20.0 < VIX <= 25.0): High-volatility market — only Tier 1 Gold setups are permitted.
  Tier 2 and Tier 3 setups are suppressed to avoid whipsaws.
- Normal Regime (11.5 <= VIX <= 20.0): All valid trade setups (T1 Gold, T2 Core, T3 Momentum) are allowed.
- Compressed Low-VIX Regime (VIX < 11.5): Theta drag floor — only Tier 1 Gold setups are permitted.
  Tier 2 and Tier 3 setups are suppressed due to stagnant premium velocity and severe theta erosion.

Includes a thread-safe 60-second in-memory TTL cache to avoid redundant Kite API calls.
"""

import logging
import time
import threading
import json
import os
import paths

_VIX_CACHE = {
    "value": None,
    "last_fetched": 0.0,
    "lock": threading.Lock()
}
_VIX_CACHE_TTL_SECONDS = 60.0


def get_india_vix(kite=None, force_refresh=False):
    """
    Fetch current India VIX quote from Zerodha Kite Connect.
    Returns float (e.g. 14.85) or None if fetch fails and no cache exists.
    Caches result for 60 seconds.
    """
    now = time.time()
    with _VIX_CACHE["lock"]:
        if not force_refresh and _VIX_CACHE["value"] is not None:
            if (now - _VIX_CACHE["last_fetched"]) < _VIX_CACHE_TTL_SECONDS:
                return _VIX_CACHE["value"]

    if not kite:
        return _VIX_CACHE["value"]

    try:
        from session import safe_kite_call
        # Try fetching by tradingsymbol first, then by token (264969)
        quote_res = safe_kite_call(kite.ltp, ["NSE:INDIA VIX"])
        vix_val = None
        if quote_res and "NSE:INDIA VIX" in quote_res:
            vix_val = float(quote_res["NSE:INDIA VIX"]["last_price"])
        else:
            quote_res = safe_kite_call(kite.ltp, [264969])
            if quote_res and 264969 in quote_res:
                vix_val = float(quote_res[264969]["last_price"])
            elif quote_res and str(264969) in quote_res:
                vix_val = float(quote_res[str(264969)]["last_price"])

        if vix_val is not None and vix_val > 0:
            with _VIX_CACHE["lock"]:
                _VIX_CACHE["value"] = round(vix_val, 2)
                _VIX_CACHE["last_fetched"] = now
            return _VIX_CACHE["value"]
    except Exception as e:
        logging.debug(f"[VIX_GUARD] Failed to fetch live India VIX quote: {e}")

    return _VIX_CACHE["value"]


def evaluate_vix_regime(kite=None, tier_val=2, config=None, vix_value=None, **kwargs):
    """
    Evaluate whether a trade setup is allowed under current India VIX regime.

    Parameters:
    - kite: KiteConnect instance (optional)
    - tier_val: int (1 = TIER_1_GOLD, 2 = TIER_2_CORE, 3 = TIER_3_MOMENTUM)
    - config: dict or None (program config overrides)
    - vix_value: float or None (direct VIX override for testing)

    Returns:
    - (is_allowed: bool, reason: str, vix_value: float | None)
    """
    if "candidate_tier" in kwargs:
        tier_val = kwargs["candidate_tier"]
    elif "tier" in kwargs:
        tier_val = kwargs["tier"]

    # Robust tier normalization (handles 1, "1", "🥇 T1", "TIER_1_GOLD", etc.)
    resolved_tier = 2
    if tier_val is not None:
        if isinstance(tier_val, (int, float)):
            resolved_tier = int(tier_val)
        else:
            ts = str(tier_val).strip().upper()
            if "1" in ts or "GOLD" in ts:
                resolved_tier = 1
            elif "3" in ts or "MOMENTUM" in ts:
                resolved_tier = 3
            elif "2" in ts or "CORE" in ts:
                resolved_tier = 2
            else:
                try:
                    resolved_tier = int(float(ts))
                except Exception:
                    resolved_tier = 2

    if config is None:
        try:
            if os.path.exists(paths.PROGRAM_CONFIG_FILE):
                with open(paths.PROGRAM_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg_all = json.load(f)
                    config = cfg_all.get("vix_guard", {})
        except Exception:
            config = {}

    vix_cfg = config.get("vix_guard", config) if isinstance(config, dict) else {}
    if not isinstance(vix_cfg, dict):
        vix_cfg = {}

    enabled = vix_cfg.get("enable", True)
    if not enabled:
        return True, "VIX_GUARD_DISABLED", None

    t2_t3_cutoff = float(vix_cfg.get("t2_t3_cutoff", 20.0))
    extreme_cutoff = float(vix_cfg.get("extreme_cutoff", 25.0))
    low_vix_floor = float(vix_cfg.get("low_vix_floor", 11.5))

    if vix_value is not None:
        vix_val = float(vix_value)
    else:
        vix_val = get_india_vix(kite)

    fail_open = bool(vix_cfg.get("fail_open", False))

    if vix_val is None or vix_val <= 0:
        if not fail_open:
            return False, "VIX_DATA_UNAVAILABLE_BLOCKED (fail_open=False)", None
        # If VIX is unreachable, do not block trading
        return True, "VIX_DATA_UNAVAILABLE_PERMITTED", None

    # Case 1: Extreme Volatility Regime (VIX > 25.0) -> Block all entries
    if vix_val > extreme_cutoff:
        return False, f"EXTREME_VIX_REGIME (VIX {vix_val:.2f} > {extreme_cutoff:.1f}) - All entries blocked", vix_val

    # Case 2: High Volatility Regime (20.0 < VIX <= 25.0) -> Allow only Tier 1 Gold
    if vix_val > t2_t3_cutoff:
        if resolved_tier <= 1:
            return True, f"HIGH_VIX_TIER1_APPROVED (VIX {vix_val:.2f} > {t2_t3_cutoff:.1f}, Tier 1 Gold exempt)", vix_val
        else:
            return False, f"HIGH_VIX_T2_T3_SUPPRESSED (VIX {vix_val:.2f} > {t2_t3_cutoff:.1f} requires Tier 1 Gold)", vix_val

    # Case 3: Compressed Low-VIX Regime (VIX < 11.5) -> Theta Drag Floor: Only Tier 1 Gold allowed
    if vix_val < low_vix_floor:
        if resolved_tier <= 1:
            return True, f"LOW_VIX_TIER1_APPROVED (VIX {vix_val:.2f} < {low_vix_floor:.1f}, Tier 1 Gold permitted under theta drag floor)", vix_val
        else:
            return False, f"LOW_VIX_THETA_FLOOR_SUPPRESSED (VIX {vix_val:.2f} < {low_vix_floor:.1f} compresses option premium velocity; Tier 2/3 suppressed)", vix_val

    # Case 4: Normal Regime (11.5 <= VIX <= 20.0) -> All tiers allowed
    return True, f"NORMAL_VIX_REGIME ({low_vix_floor:.1f} <= VIX {vix_val:.2f} <= {t2_t3_cutoff:.1f})", vix_val
