import os
import json
import logging
import paths
from datetime import datetime as dt


def sanitize_sl_and_entry(entry_spot, current_sl, trailing_stage=0, side="BULL", high_price=0.0):
    """
    Ensure Stop-Loss is mathematically valid and never inverted on untrailed or corrupted positions.
    - Bullish/CE: current_sl must be strictly below entry_spot (unless trailing_stage >= 1 AND high_price >= current_sl).
    - Bearish/PE: current_sl must be strictly above entry_spot (unless trailing_stage >= 1 AND high_price <= current_sl).
    """
    try:
        from targets import calculate_sl_buffer
    except Exception:
        def calculate_sl_buffer(p, s="BULL"):
            return round(p * 0.85, 2) if s == "BULL" else round(p * 1.15, 2)

    try:
        entry = float(entry_spot or 0.0)
        sl = float(current_sl or 0.0)
        hp = float(high_price or 0.0)
        if entry <= 0:
            return entry, sl

        is_bull = str(side).upper() in ["BULL", "CE", "BUY"]
        stage = int(trailing_stage or 0)

        if is_bull:
            # If SL >= Entry, it is ONLY valid if the trade has reached stage >= 1 AND highest price touched was >= SL!
            # If price never reached SL (e.g. stale SL 24.70 on entry 16.00 with high 18.90), it is a corrupted ghost SL.
            if sl >= entry:
                if stage == 0 or (hp > 0 and hp < sl) or sl > (entry * 1.30):
                    sl = calculate_sl_buffer(entry, side="BULL")
        else:
            if sl <= entry and sl > 0:
                if stage == 0 or (hp > 0 and hp > sl) or sl < (entry * 0.70):
                    sl = calculate_sl_buffer(entry, side="BEAR")
        return entry, round(sl, 2)
    except Exception:
        return entry_spot, current_sl


def _atomic_write_json(file_path, data):
    tmp = f"{file_path}.tmp.{os.getpid()}"
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        for attempt in range(5):
            try:
                os.replace(tmp, file_path)
                return True
            except (PermissionError, OSError):
                time.sleep(0.05 * (attempt + 1))
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logging.warning(f"Atomic write failed for {file_path}: {e}")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return True
        except Exception:
            return False
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


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
        _atomic_write_json(paths.SL_TARGET_OVERRIDES_FILE, cleaned)
        logging.info("[OVERRIDES] Cleaned stale/expired and inverted overrides.")
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
        _atomic_write_json(paths.SL_TARGET_OVERRIDES_FILE, overrides)


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
    _atomic_write_json(paths.SL_TARGET_OVERRIDES_FILE, overrides)
    return overrides

