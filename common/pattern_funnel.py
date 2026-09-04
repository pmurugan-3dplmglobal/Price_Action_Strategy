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
    sym = item.get("symbol", "")
    cntr = item.get("contract") or sym
    side = item.get("side", "CE")
    strike = item.get("strike", "")
    return f"{sym}|{cntr}|{side}|{strike}"

def load_funnel_state(engine_name=None):
    """Load the full pattern funnel state from disk."""
    global _mem_cache
    with _funnel_lock:
        fpath = paths.PATTERN_FUNNEL_FILE
        if os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        _mem_cache = data
            except Exception as e:
                logger.warning(f"[FUNNEL] Failed to read {fpath}: {e}")
        if engine_name:
            return _mem_cache.get(engine_name, {"category_a_plus": [], "category_a": [], "category_b": [], "updated_at": ""})
        return _mem_cache

def save_funnel_state(engine_name, data):
    """Atomically write funnel data for a given engine to disk."""
    global _mem_cache
    with _funnel_lock:
        if not isinstance(_mem_cache, dict):
            _mem_cache = {}
        _mem_cache[engine_name] = data
        _mem_cache[engine_name]["updated_at"] = get_ist_now().strftime("%Y-%m-%d %H:%M:%S")

        fpath = paths.PATTERN_FUNNEL_FILE
        tmp_path = f"{fpath}.tmp"
        try:
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(_mem_cache, f, indent=2)
            os.replace(tmp_path, fpath)
        except Exception as e:
            logger.error(f"[FUNNEL] Failed to save {fpath}: {e}")
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

def update_funnel(engine_name, a_plus_items=None, a_items=None, b_items=None):
    """Update or merge items into Category A+, Category A, and Category B for an engine."""
    with _funnel_lock:
        current = load_funnel_state(engine_name)
        
        # Build maps for fast deduplication and stage migration
        a_plus_map = {_get_key(x): x for x in (a_plus_items or current.get("category_a_plus", []))}
        a_map = {_get_key(x): x for x in (a_items or current.get("category_a", []))}
        b_map = {_get_key(x): x for x in (b_items or current.get("category_b", []))}

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
    """Promote an item to a higher maturity category (e.g. B -> A or A -> A+)."""
    with _funnel_lock:
        current = load_funnel_state(engine_name)
        key = _get_key(item)
        
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
