import os
import json
import paths


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
    Writes both the raw symbol and its cleaned (uppercase, no-space) form under
    every engine alias so all dashboards/engines can look it up.
    """
    overrides = read_sl_overrides()
    clean_symbol = str(symbol).replace(" ", "").upper()
    for eng_k in engine_aliases:
        overrides.setdefault(eng_k, {})[str(symbol)] = vals
        overrides.setdefault(eng_k, {})[clean_symbol] = vals
    os.makedirs(os.path.dirname(paths.SL_TARGET_OVERRIDES_FILE), exist_ok=True)
    with open(paths.SL_TARGET_OVERRIDES_FILE, "w", encoding="utf-8") as f:
        json.dump(overrides, f, indent=2)
    return overrides
