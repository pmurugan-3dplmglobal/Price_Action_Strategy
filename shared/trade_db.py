import json, os, time, threading

TRADES_DB = os.path.join("output", "monitor", "trades_db.json")

def _read():
    if not os.path.exists(TRADES_DB):
        return {"next_id": 1, "trades": []}
    for _ in range(3):
        try:
            with open(TRADES_DB, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            time.sleep(0.05)
    return {"next_id": 1, "trades": []}

def _write(db):
    os.makedirs(os.path.dirname(TRADES_DB), exist_ok=True)
    tmp = TRADES_DB + ".tmp"
    for _ in range(3):
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(db, f, indent=2)
            os.replace(tmp, TRADES_DB)
            return
        except:
            time.sleep(0.05)

def create_trade(engine, symbol, data, entry_time=None):
    db = _read()
    tid = db["next_id"]
    db["next_id"] = tid + 1
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    trade = {"id": tid, "engine": engine, "symbol": symbol, "status": "ACTIVE", "created_at": now, "entry_time": entry_time or now}
    trade.update(data)
    db["trades"].append(trade)
    _write(db)
    return tid

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


# ---- Cycle staging + executed-pattern registry (multi-cycle dedup) ----

CYCLE_STORE_FILE = os.path.join("output", "monitor", "cycle_trades.json")
EXECUTED_STORE_FILE = os.path.join("output", "monitor", "executed_patterns.json")

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
    db.setdefault(engine, [])
    db[engine].append(trade)
    _write_json(CYCLE_STORE_FILE, db)


def get_cycle_trades(engine):
    return _read_json(CYCLE_STORE_FILE, {}).get(engine, [])


def clear_cycle_trades(engine):
    db = _read_json(CYCLE_STORE_FILE, {})
    if engine in db:
        db[engine] = []
        _write_json(CYCLE_STORE_FILE, db)


def _load_executed_cache():
    global _executed_cache
    if _executed_cache is None:
        _executed_cache = _read_json(EXECUTED_STORE_FILE, {})
    return _executed_cache


def is_pattern_executed(engine, key):
    """True if this pattern key was already executed in a previous cycle. Uses in-memory cache."""
    with _executed_cache_lock:
        return key in _load_executed_cache().get(engine, {})


def clear_executed_patterns():
    """Wipe all executed pattern records (used when journal is cleared)."""
    global _executed_cache
    with _executed_cache_lock:
        _executed_cache = {}
        _write_json(EXECUTED_STORE_FILE, {})
        _write_json(CYCLE_STORE_FILE, {})


def record_executed_pattern(engine, key, info=None):
    """Records an executed pattern and updates both cache + disk atomically."""
    with _executed_cache_lock:
        db = _load_executed_cache()
        db.setdefault(engine, {})
        db[engine][key] = info or {"executed_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        _write_json(EXECUTED_STORE_FILE, db)


def unrecord_executed_pattern(engine, key):
    """Removes an executed pattern record (e.g. when a pending order is cancelled)."""
    with _executed_cache_lock:
        db = _load_executed_cache()
        if engine in db and key in db[engine]:
            del db[engine][key]
            _write_json(EXECUTED_STORE_FILE, db)