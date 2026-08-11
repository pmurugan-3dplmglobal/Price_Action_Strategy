import json, os, time, threading

import paths

TRADES_DB = paths.TRADES_DB

def _read():
    if not os.path.exists(TRADES_DB):
        return {"next_id": 1, "trades": []}
    for _ in range(3):
        try:
            with open(TRADES_DB, "r", encoding="utf-8") as f:
                db = json.load(f)
                if "trades" not in db:
                    db["trades"] = []
                if "next_id" not in db:
                    db["next_id"] = 1
                return db
        except:
            time.sleep(0.05)
    return {"next_id": 1, "trades": []}

ACTIVE_POSITIONS_DB = paths.ACTIVE_POSITIONS_DB
SCANNED_TRADES_DB = paths.SCANNED_TRADES_DB
JOURNAL_TRADES_DB = paths.JOURNAL_TRADES_DB

def _sync_tab_databases(db):
    try:
        trades = db.get("trades", [])
        active_trades = [t for t in trades if t.get("status") == "ACTIVE"]
        completed_trades = [t for t in trades if t.get("status") != "ACTIVE"]
        
        _write_json(ACTIVE_POSITIONS_DB, {"updated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "positions": active_trades})
        _write_json(JOURNAL_TRADES_DB, {"updated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "journal_entries": completed_trades})
    except Exception as e:
        pass

def _write(db):
    os.makedirs(os.path.dirname(TRADES_DB), exist_ok=True)
    tmp = TRADES_DB + ".tmp"
    for _ in range(3):
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(db, f, indent=2)
            os.replace(tmp, TRADES_DB)
            _sync_tab_databases(db)
            return
        except:
            time.sleep(0.05)

def _normalize_contract(contract):
    return str(contract or "").replace(" ", "").upper()


def create_trade(engine, symbol, data, allow_duplicate=False):
    """Create a new trade. Rejects duplicate ACTIVE contracts for the same engine.

    Returns (trade_id, created_bool). If an ACTIVE trade with the same contract
    already exists, returns the existing id with created_bool=False.
    """
    db = _read()
    contract = _normalize_contract(data.get("contract") or symbol)
    if not allow_duplicate and contract:
        for t in db["trades"]:
            if t.get("status") == "ACTIVE" and _normalize_contract(t.get("contract") or t.get("symbol")) == contract and t.get("engine") == engine:
                return t["id"], False
    tid = db["next_id"]
    db["next_id"] = tid + 1
    trade = {"id": tid, "engine": engine, "symbol": symbol, "status": "ACTIVE", "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    trade.update(data)
    db["trades"].append(trade)
    _write(db)
    return tid, True

def update_trade(trade_id, updates):
    db = _read()
    for t in db["trades"]:
        if t["id"] == trade_id:
            t.update(updates)
            t["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            break
    _write(db)

def get_active_trades(engine=None):
    db = _read()
    return [t for t in db["trades"] if t.get("status") == "ACTIVE" and (engine is None or t.get("engine") == engine)]

def get_all_trades(engine=None):
    db = _read()
    if engine:
        return [t for t in db["trades"] if t.get("engine") == engine]
    return db["trades"]

def get_completed_trades():
    db = _read()
    return [t for t in db["trades"] if t.get("status") != "ACTIVE"]

def remove_trades(trade_ids):
    db = _read()
    db["trades"] = [t for t in db["trades"] if t["id"] not in trade_ids]
    _write(db)


def _parse_embedded_expiry(contract):
    """Best-effort expiry date from contract name (YY + [M]M + DD + strike + side)."""
    from datetime import datetime
    import re
    try:
        m = re.search(r"(\d+)(CE|PE)$", str(contract).upper())
        if not m:
            return None
        num_part = m.group(1)
        for strike_len in range(6, 2, -1):
            if len(num_part) <= strike_len:
                continue
            date_part = num_part[:len(num_part) - strike_len]
            if len(date_part) < 5:
                continue
            for mm_width in (2, 1):
                if len(date_part) != 2 + mm_width + 2:
                    continue
                yy = int(date_part[:2])
                mm = int(date_part[2:2 + mm_width])
                dd = int(date_part[2 + mm_width:])
                if 1 <= mm <= 12 and 1 <= dd <= 31:
                    return datetime.strptime("20%02d-%02d-%02d" % (yy, mm, dd), "%Y-%m-%d").date()
    except Exception:
        pass
    return None


def purge_expired_positions(expiry_cutoff=None):
    """Remove ACTIVE trades whose contract has expired.

    expiry_cutoff: a date string 'YYYY-MM-DD'. If None, derives a cutoff from the
    contract's embedded expiry where parseable. Returns count removed.
    """
    from datetime import datetime
    db = _read()
    today = datetime.now().date()
    kept = []
    removed = 0
    for t in db["trades"]:
        if t.get("status") != "ACTIVE":
            kept.append(t)
            continue
        contract = str(t.get("contract") or t.get("symbol") or "")
        exp_date = _parse_embedded_expiry(contract)
        if exp_date is not None and exp_date < today:
            removed += 1
            continue
        if expiry_cutoff and (t.get("created_at", "")[:10] < expiry_cutoff):
            removed += 1
            continue
        kept.append(t)
    if removed:
        db["trades"] = kept
        _write(db)
    return removed


def dedupe_active_positions():
    """Collapse duplicate ACTIVE rows for the same engine+contract, keeping the newest."""
    db = _read()
    seen = {}
    kept = []
    removed = 0
    for t in db["trades"]:
        if t.get("status") == "ACTIVE":
            key = (t.get("engine"), _normalize_contract(t.get("contract") or t.get("symbol")))
            if key in seen:
                removed += 1
                continue
            seen[key] = t
        kept.append(t)
    if removed:
        db["trades"] = kept
        _write(db)
    return removed


# ---- Cycle staging + executed-pattern registry (multi-cycle dedup) ----

CYCLE_STORE_FILE = paths.CYCLE_STORE_FILE
EXECUTED_STORE_FILE = paths.EXECUTED_STORE_FILE

_executed_cache = None
_executed_cache_lock = threading.Lock()


def _read_json(path, default):
    if not os.path.exists(path):
        return default
    for _ in range(3):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            time.sleep(0.05)
    return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    for _ in range(3):
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, path)
            return
        except Exception:
            time.sleep(0.05)


def stage_cycle_trade(engine, trade):
    """Persist a found trade into per-engine temp storage for the current cycle."""
    db = _read_json(CYCLE_STORE_FILE, {})
    if not isinstance(db, dict):
        db = {}
    db.setdefault(engine, [])
    db[engine].append(trade)
    _write_json(CYCLE_STORE_FILE, db)


def get_cycle_trades(engine):
    db = _read_json(CYCLE_STORE_FILE, {})
    if not isinstance(db, dict):
        return []
    return db.get(engine, [])


def clear_cycle_trades(engine):
    db = _read_json(CYCLE_STORE_FILE, {})
    if not isinstance(db, dict):
        db = {}
    db[engine] = []
    _write_json(CYCLE_STORE_FILE, db)


def _load_executed_cache():
    global _executed_cache
    if _executed_cache is None or not isinstance(_executed_cache, dict):
        _executed_cache = _read_json(EXECUTED_STORE_FILE, {})
        if not isinstance(_executed_cache, dict):
            _executed_cache = {}
    return _executed_cache


def is_pattern_executed(engine, key):
    """True if this pattern key was already executed in a previous cycle. Uses in-memory cache."""
    with _executed_cache_lock:
        cache = _load_executed_cache()
        return key in cache.get(engine, {})


def record_executed_pattern(engine, key, info=None):
    """Records an executed pattern and updates both cache + disk atomically."""
    with _executed_cache_lock:
        db = _load_executed_cache()
        if not isinstance(db, dict):
            db = {}
        db.setdefault(engine, {})
        db[engine][key] = info or {"executed_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        _write_json(EXECUTED_STORE_FILE, db)
