"""
common/pattern_funnel.py — Price Action Lifecycle Funnel Manager (Categories A+, A, B)

Manages the multi-stage incubation radar across trading engines:
  • Category A+ (⚡ Imminent Breakout / Institutional Gold):
      Phase 0 Parabolic Multi-Swing (>= 3 waves, R^2 >= 0.55, Terminal Base)
      + Anchor A + Breakout B + Retracement C formed. Coiled at Benchmark D trigger.
  • Category A (🎯 Core Pre-Breakout):
      Valid Anchor A + Breakout B + Retracement C formed. Ready for D breakout.
  • Category B (🌱 Anchor Incubation Base):
      Valid Anchor A formed (Engulfing, Sweep, Hammer, Harami, Two HH/LL, Base).
      Pullback B and Retracement C still developing. Active & uninvalidated.

Thread-safe and atomically persisted to paths.PATTERN_FUNNEL_FILE.
"""

import os
import json
import logging
import threading
import time
from datetime import datetime as dt

try:
    import paths
    from timeframe_utils import get_ist_now
    from display_writer import clean_timestamp
except ImportError:
    from common import paths
    from common.timeframe_utils import get_ist_now
    from common.display_writer import clean_timestamp

logger = logging.getLogger(__name__)

_funnel_lock = threading.RLock()
_mem_cache = {}

STAGE_A_PLUS = "A_PLUS"
STAGE_A = "A"
STAGE_B = "B"

def _get_key(item):
    """
    Returns unique key per underlying asset and direction: {symbol}|{side}.
    Guarantees Single Best-Strike Invariant: A symbol cannot occupy multiple slots
    in the radar funnel with different strikes.
    """
    sym = str(item.get("symbol") or "").strip().upper()
    side = str(item.get("side") or "CE").strip().upper()
    return f"{sym}|{side}"

def _is_better_setup(new_item, old_item):
    """
    Evaluates which contract is quantitatively superior for the same (symbol, side).
    Priority:
      1. Tier Conviction: Tier 1 (Gold) > Tier 2 (Core) > Tier 3 (Momentum)
      2. Risk-to-Reward (R:R): Higher R:R is better
      3. VCP Compression: Tighter ATR contraction ratio or active squeeze is better
    """
    if not old_item:
        return True

    # 1. Tier comparison (lower number = higher conviction: 1 < 2 < 3)
    t_new = int(new_item.get("tier") or 2)
    t_old = int(old_item.get("tier") or 2)
    if t_new != t_old:
        return t_new < t_old

    # 2. R:R comparison
    try:
        rr_new = float(new_item.get("rr") or 0.0)
        rr_old = float(old_item.get("rr") or 0.0)
        if abs(rr_new - rr_old) >= 0.05:
            return rr_new > rr_old
    except (ValueError, TypeError):
        pass

    # 3. Squeeze comparison
    sq_new = bool(new_item.get("is_squeeze", False))
    sq_old = bool(old_item.get("is_squeeze", False))
    if sq_new and not sq_old:
        return True
    if sq_old and not sq_new:
        return False

    # 4. VCP ATR contraction ratio (lower is tighter)
    try:
        atr_new = float(new_item.get("atr_ratio") or 1.0)
        atr_old = float(old_item.get("atr_ratio") or 1.0)
        if abs(atr_new - atr_old) >= 0.05:
            return atr_new < atr_old
    except (ValueError, TypeError):
        pass

    return True

def load_funnel_state(engine_name=None):
    """Load the full pattern funnel state from disk with retry on read lock."""
    global _mem_cache
    with _funnel_lock:
        fpath = paths.PATTERN_FUNNEL_FILE
        if os.path.exists(fpath):
            for attempt in range(3):
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict):
                            _mem_cache = data
                    break
                except (PermissionError, OSError, json.JSONDecodeError) as e:
                    time.sleep(0.05 * (attempt + 1))
                except Exception as e:
                    logger.warning(f"[FUNNEL] Failed to read {fpath}: {e}")
                    break
        if engine_name:
            return _mem_cache.get(engine_name, {"category_a_plus": [], "category_a": [], "category_b": [], "updated_at": ""})
        return _mem_cache

def save_funnel_state(engine_name, data):
    """Atomically write funnel data for a given engine to disk with Windows file-lock retry."""
    global _mem_cache
    with _funnel_lock:
        if not isinstance(_mem_cache, dict):
            _mem_cache = {}
        _mem_cache[engine_name] = data
        _mem_cache[engine_name]["updated_at"] = get_ist_now().strftime("%Y-%m-%d %H:%M:%S")

        fpath = paths.PATTERN_FUNNEL_FILE
        tmp_path = f"{fpath}.tmp.{os.getpid()}.{threading.get_ident()}"
        written = False
        try:
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(_mem_cache, f, indent=2)
            for attempt in range(5):
                try:
                    os.replace(tmp_path, fpath)
                    written = True
                    break
                except (PermissionError, OSError):
                    time.sleep(0.05 * (attempt + 1))
            if not written:
                with open(fpath, "w", encoding="utf-8") as f:
                    json.dump(_mem_cache, f, indent=2)
        except Exception as e:
            try:
                with open(fpath, "w", encoding="utf-8") as f:
                    json.dump(_mem_cache, f, indent=2)
            except Exception as direct_err:
                logger.error(f"[FUNNEL] Failed to save {fpath}: {direct_err}")
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

def update_funnel(engine_name, a_plus_items=None, a_items=None, b_items=None):
    """Update or merge items into Category A+, Category A, and Category B for an engine with best-strike deduplication."""
    with _funnel_lock:
        current = load_funnel_state(engine_name)

        def _dedup_list(items):
            best_map = {}
            for x in items:
                k = _get_key(x)
                if k not in best_map or _is_better_setup(x, best_map[k]):
                    best_map[k] = x
            return best_map

        a_plus_map = _dedup_list(a_plus_items or current.get("category_a_plus", []))
        a_map = _dedup_list(a_items or current.get("category_a", []))
        b_map = _dedup_list(b_items or current.get("category_b", []))

        # Enforce exclusivity: If an item is in A+, remove from A and B
        for k in a_plus_map:
            a_map.pop(k, None)
            b_map.pop(k, None)

        # If in A, remove from B
        for k in a_map:
            b_map.pop(k, None)

        updated = {
            "category_a_plus": list(a_plus_map.values()),
            "category_a": list(a_map.values()),
            "category_b": list(b_map.values()),
        }
        save_funnel_state(engine_name, updated)
        logger.info(
            f"[FUNNEL UPDATE] {engine_name}: A+={len(updated['category_a_plus'])}, "
            f"A={len(updated['category_a'])}, B={len(updated['category_b'])}"
        )
        return updated

def promote_item(engine_name, item, target_stage):
    """Promote an item to a higher maturity category (e.g. B -> A or A -> A+) with best-strike deduplication."""
    with _funnel_lock:
        current = load_funnel_state(engine_name)
        key = _get_key(item)

        # Check if an existing setup for this (symbol, side) already exists
        existing = None
        for pool in [current.get("category_a_plus", []), current.get("category_a", []), current.get("category_b", [])]:
            for x in pool:
                if _get_key(x) == key:
                    existing = x
                    break
            if existing:
                break

        stage_rank = {STAGE_A_PLUS: 3, STAGE_A: 2, STAGE_B: 1}
        if existing:
            existing_rank = stage_rank.get(existing.get("stage", STAGE_B), 1)
            target_rank = stage_rank.get(target_stage, 1)
            # If existing setup is already at a more mature stage, keep existing
            if existing_rank > target_rank:
                return current
            # If same maturity stage but existing setup has better conviction/RR, keep existing
            if existing_rank == target_rank and not _is_better_setup(item, existing):
                return current

        a_plus_list = [x for x in current.get("category_a_plus", []) if _get_key(x) != key]
        a_list = [x for x in current.get("category_a", []) if _get_key(x) != key]
        b_list = [x for x in current.get("category_b", []) if _get_key(x) != key]

        item_copy = item.copy()
        item_copy["stage"] = target_stage
        item_copy["promoted_at"] = get_ist_now().strftime("%Y-%m-%d %H:%M:%S")

        if target_stage == STAGE_A_PLUS:
            a_plus_list.append(item_copy)
        elif target_stage == STAGE_A:
            a_list.append(item_copy)
        elif target_stage == STAGE_B:
            b_list.append(item_copy)

        updated = {
            "category_a_plus": a_plus_list,
            "category_a": a_list,
            "category_b": b_list,
        }
        save_funnel_state(engine_name, updated)
        return updated

def register_partial_pattern(engine_name, item, stage):
    """Register or update an incubating setup at the given stage (A_PLUS, A, or B)."""
    return promote_item(engine_name, item, stage)

def _matches_evict(x, item_or_key):
    if isinstance(item_or_key, dict):
        return _get_key(x) == _get_key(item_or_key)
    target = str(item_or_key).strip().upper()
    x_key = _get_key(x).upper()
    x_cntr = str(x.get("contract") or "").strip().upper()
    x_sym = str(x.get("symbol") or "").strip().upper()
    return target == x_key or target == x_cntr or target == x_sym

def evict_item(engine_name, item_or_key):
    """Remove an invalidated or executed item from all funnel categories (by dict, key, contract, or symbol)."""
    with _funnel_lock:
        current = load_funnel_state(engine_name)

        updated = {
            "category_a_plus": [x for x in current.get("category_a_plus", []) if not _matches_evict(x, item_or_key)],
            "category_a": [x for x in current.get("category_a", []) if not _matches_evict(x, item_or_key)],
            "category_b": [x for x in current.get("category_b", []) if not _matches_evict(x, item_or_key)],
        }
        save_funnel_state(engine_name, updated)
        return updated

def clear_funnel(engine_name):
    """Clear all funnel categories for an engine (e.g., at morning pre-flight reset)."""
    with _funnel_lock:
        updated = {"category_a_plus": [], "category_a": [], "category_b": []}
        save_funnel_state(engine_name, updated)
        return updated

def get_funnel_summary(engine_name):
    """Return counts and quick stats for UI dashboards."""
    with _funnel_lock:
        state = load_funnel_state(engine_name)
        return {
            "engine": engine_name,
            "updated_at": state.get("updated_at", ""),
            "count_a_plus": len(state.get("category_a_plus", [])),
            "count_a": len(state.get("category_a", [])),
            "count_b": len(state.get("category_b", [])),
            "total_incubating": (
                len(state.get("category_a_plus", []))
                + len(state.get("category_a", []))
                + len(state.get("category_b", []))
            ),
            "category_a_plus": state.get("category_a_plus", []),
            "category_a": state.get("category_a", []),
            "category_b": state.get("category_b", [])
        }
