import os
import json
import logging
import paths
from datetime import datetime as dt


def sanitize_sl_and_entry(entry_spot, current_sl, trailing_stage=0, side="BULL"):
    """
    Ensure Stop-Loss is mathematically valid and never inverted on untrailed positions.
    - Bullish/CE: current_sl must be strictly below entry_spot (unless trailing_stage >= 1).
    - Bearish/PE: current_sl must be strictly above entry_spot (unless trailing_stage >= 1).
    """
    try:
        entry = float(entry_spot or 0.0)
        sl = float(current_sl or 0.0)
        if entry <= 0:
            return entry, sl

        is_bull = str(side).upper() in ["BULL", "CE", "BUY"]
        stage = int(trailing_stage or 0)

        if is_bull:
            if stage == 0 and sl >= entry:
                sl = round(entry * 0.95, 2)
        else:
            if stage == 0 and sl <= entry and sl > 0:
                sl = round(entry * 1.05, 2)
        return entry, sl
    except Exception:
        return entry_spot, current_sl


def clean_stale_overrides(active_contracts=None):
    """
    Purge expired contracts and invalid/inverted entries from sl_target_overrides.json.
    """
    try:
        from position_monitor import contract_is_expired
    except Exception:
        def contract_is_expired(c):
            return "26AUG" in str(c).upper()

    overrides = read_sl_overrides()
    cleaned = {}
    modified = False

    for eng, sym_dict in overrides.items():
        if not isinstance(sym_dict, dict):
            continue
        cleaned[eng] = {}
        for sym, vals in sym_dict.items():
            if not isinstance(vals, dict):
                continue
            # 1. Skip expired contracts
            if contract_is_expired(sym):
                modified = True
                continue
            
            # 2. Inverted SL check for non-trailed overrides
            e_val = float(vals.get("entry_spot") or 0.0)
            sl_val = float(vals.get("current_sl") or 0.0)
            stage_val = int(vals.get("trailing_stage") or 0)
            if e_val > 0 and sl_val >= e_val and stage_val == 0:
                modified = True
                continue # Purge inverted override

            cleaned[eng][sym] = vals

    if modified:
        try:
            os.makedirs(os.path.dirname(paths.SL_TARGET_OVERRIDES_FILE), exist_ok=True)
            tmp = paths.SL_TARGET_OVERRIDES_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cleaned, f, indent=2)
            os.replace(tmp, paths.SL_TARGET_OVERRIDES_FILE)
            logging.info("[OVERRIDES] Cleaned stale/expired and inverted overrides.")
        except Exception as e:
            logging.warning(f"[OVERRIDES] Failed to write cleaned overrides: {e}")
    return cleaned


def purge_sl_override(symbol):
    """Purge a specific symbol or contract across all engines in sl_target_overrides.json."""
    if not symbol:
        return
    overrides = read_sl_overrides()
    clean_symbol = str(symbol).replace(" ", "").upper()
    modified = False
    for eng in list(overrides.keys()):
        if str(symbol) in overrides[eng]:
            overrides[eng].pop(str(symbol), None)
            modified = True
        if clean_symbol in overrides[eng]:
            overrides[eng].pop(clean_symbol, None)
            modified = True
    if modified:
        try:
            tmp = paths.SL_TARGET_OVERRIDES_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(overrides, f, indent=2)
            os.replace(tmp, paths.SL_TARGET_OVERRIDES_FILE)
        except Exception as e:
            logging.warning(f"Failed to purge override for {symbol}: {e}")


def read_sl_overrides():
    """Load user-edited SL/T1/T2/T3 overrides from the canonical overrides file."""
    overrides = {}
    try:
        if os.path.exists(paths.SL_TARGET_OVERRIDES_FILE):
            with open(paths.SL_TARGET_OVERRIDES_FILE, "r", encoding="utf-8") as f:
                overrides = json.load(f)
    except Exception:
        overrides = {}
    return overrides


def write_sl_overrides(engine, symbol, vals, engine_aliases):
    """
    Persist a user-edited position override (SL/T1/T2/T3) for the given symbol.
    Sanitizes values to prevent inverted SL (SL > Entry on Long positions).
    """
    overrides = read_sl_overrides()
    clean_symbol = str(symbol).replace(" ", "").upper()
    
    # Sanitize SL vs Entry
    e_val = float(vals.get("entry_spot") or vals.get("entry_price") or 0.0)
    sl_val = float(vals.get("current_sl") or 0.0)
    st_val = int(vals.get("trailing_stage") or 0)
    if e_val > 0 and sl_val > 0:
        _, safe_sl = sanitize_sl_and_entry(e_val, sl_val, st_val, vals.get("side", "CE"))
        vals["current_sl"] = safe_sl

    for eng_k in engine_aliases:
        overrides.setdefault(eng_k, {})[str(symbol)] = vals
        overrides.setdefault(eng_k, {})[clean_symbol] = vals
    os.makedirs(os.path.dirname(paths.SL_TARGET_OVERRIDES_FILE), exist_ok=True)
    tmp = paths.SL_TARGET_OVERRIDES_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(overrides, f, indent=2)
    os.replace(tmp, paths.SL_TARGET_OVERRIDES_FILE)
    return overrides

