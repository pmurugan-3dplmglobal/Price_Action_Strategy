"""
trade_db.py — SQLite-backed trade database with WAL mode + ACID transactions.

Migration from JSON-based storage (2026-08-11):
  - Uses SQLite WAL mode for safe concurrent multi-process access
  - Auto-migrates existing trades_db.json on first run
  - Preserves the complete public API (create_trade, update_trade, get_active_trades, etc.)
  - Keeps tab-database JSON sync (active_positions_db.json, journal_trades_db.json)
    for dashboard compatibility
  - cycle_trades and executed_patterns remain JSON-based (small, rarely written)
"""
import logging
import json
import os
import re
import sqlite3
import time
import threading
from datetime import datetime, datetime as dt

import paths
from timeframe_utils import get_ist_now

# ── SQLite database path ──
_DB_PATH = os.path.join(os.path.dirname(paths.TRADES_DB), "trades.sqlite3")
_DB_LOCK = threading.Lock()

# ── Tab-sync JSON paths (kept for dashboard compatibility) ──
TRADES_DB = paths.TRADES_DB                        # legacy JSON (kept for migration source)
ACTIVE_POSITIONS_DB = paths.ACTIVE_POSITIONS_DB
SCANNED_TRADES_DB = paths.SCANNED_TRADES_DB
JOURNAL_TRADES_DB = paths.JOURNAL_TRADES_DB

# ── Cycle + executed-pattern stores (JSON — small, infrequent writes) ──
CYCLE_STORE_FILE = paths.CYCLE_STORE_FILE
EXECUTED_STORE_FILE = paths.EXECUTED_STORE_FILE

_executed_cache = None
_executed_cache_lock = threading.Lock()


# ════════════════════════════════════════════════════════════
#  SQLITE HELPERS
# ════════════════════════════════════════════════════════════

def _get_connection():
    """Return a SQLite connection configured with WAL mode and thread safety."""
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=10, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    """Create tables if they don't exist and migrate from JSON if needed."""
    with _get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id          INTEGER PRIMARY KEY,
                engine      TEXT,
                symbol      TEXT,
                contract    TEXT,
                status      TEXT DEFAULT 'ACTIVE',
                data_json   TEXT NOT NULL DEFAULT '{}',
                created_at  TEXT,
                updated_at  TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_status  ON trades(status);
            CREATE INDEX IF NOT EXISTS idx_engine  ON trades(engine);
            CREATE INDEX IF NOT EXISTS idx_contract ON trades(contract);
        """)
    _migrate_from_json()


def _migrate_from_json():
    """Sync trades from trades_db.json → SQLite.

    On first run (empty DB) inserts all records.
    On subsequent runs, upserts any ACTIVE records from JSON whose status in
    SQLite is stale (e.g. COMPLETED) or missing entirely.  This prevents the
    scenario where the one-time guard (`count > 0 → skip`) leaves active
    positions invisible to the dashboard.
    """
    if not os.path.exists(TRADES_DB):
        return
    try:
        with open(TRADES_DB, "r", encoding="utf-8") as f:
            legacy = json.load(f)
        trades = legacy.get("trades", [])
        if not trades:
            return

        with _get_connection() as conn:
            db_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]

            if db_count == 0:
                # Fresh migration — insert everything
                for t in trades:
                    tid = t.get("id")
                    engine = t.get("engine", "")
                    symbol = t.get("symbol", "")
                    contract = _normalize_contract(t.get("contract") or symbol)
                    status = t.get("status", "ACTIVE")
                    created_at = t.get("created_at", "")
                    updated_at = t.get("updated_at", created_at)
                    data = json.dumps(t)
                    conn.execute(
                        "INSERT OR IGNORE INTO trades (id, engine, symbol, contract, status, data_json, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (tid, engine, symbol, contract, status, data, created_at, updated_at)
                    )
                logging.info(f"[trade_db] Migrated {len(trades)} trades from JSON → SQLite")
            else:
                # Incremental sync — upsert any ACTIVE JSON records
                synced = 0
                for t in trades:
                    if t.get("status") != "ACTIVE":
                        continue
                    tid = t.get("id")
                    contract = _normalize_contract(t.get("contract") or t.get("symbol"))
                    if not tid and not contract:
                        continue

                    # Check if this record already exists and is already ACTIVE
                    existing = None
                    if tid is not None:
                        existing = conn.execute("SELECT id, status FROM trades WHERE id=?", (tid,)).fetchone()
                    if not existing and contract:
                        existing = conn.execute("SELECT id, status FROM trades WHERE contract=? LIMIT 1", (contract,)).fetchone()

                    if existing and existing["status"] == "ACTIVE":
                        continue  # Already synced and active

                    data = json.dumps(t)
                    engine = t.get("engine", "")
                    symbol = t.get("symbol", "")
                    created_at = t.get("created_at", "")
                    updated_at = t.get("updated_at", created_at)

                    if existing:
                        conn.execute(
                            "UPDATE trades SET status=?, data_json=?, updated_at=? WHERE id=?",
                            ("ACTIVE", data, updated_at, existing["id"])
                        )
                    else:
                        conn.execute(
                            "INSERT OR IGNORE INTO trades (id, engine, symbol, contract, status, data_json, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (tid, engine, symbol, contract, "ACTIVE", data, created_at, updated_at)
                        )
                    synced += 1
                if synced:
                    logging.info(f"[trade_db] Incremental sync: {synced} ACTIVE trades from JSON → SQLite")
    except Exception as e:
        logging.warning(f"[trade_db] JSON migration failed (non-fatal): {e}")


def _row_to_dict(row):
    """Convert a SQLite Row (with data_json) to a plain dict."""
    try:
        d = json.loads(row["data_json"])
    except Exception:
        d = {}
    # Ensure top-level fields are always present
    d["id"] = row["id"]
    d["engine"] = row["engine"]
    d["symbol"] = row["symbol"]
    d["contract"] = row["contract"]
    d["status"] = row["status"]
    d["created_at"] = row["created_at"]
    if row["updated_at"]:
        d["updated_at"] = row["updated_at"]
    return d


def _normalize_contract(contract):
    return str(contract or "").replace(" ", "").upper()


# ════════════════════════════════════════════════════════════
#  TAB-DATABASE JSON SYNC (for dashboard compatibility)
# ════════════════════════════════════════════════════════════

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


def _sync_tab_databases():
    """Sync active + journal JSON files from SQLite for dashboard consumption."""
    try:
        active = get_active_trades()
        completed = get_completed_trades()
        _write_json(ACTIVE_POSITIONS_DB, {
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "positions": active
        })
        _write_json(JOURNAL_TRADES_DB, {
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "journal_entries": completed
        })
    except Exception as e:
        logging.warning(f"Tab database sync failed: {e}")


# ════════════════════════════════════════════════════════════
#  PUBLIC API — identical to the old JSON-based trade_db
# ════════════════════════════════════════════════════════════

def create_trade(engine, symbol, data, allow_duplicate=False):
    """Create a new trade. Rejects duplicate ACTIVE contracts for the same engine.

    Returns (trade_id, created_bool). If an ACTIVE trade with the same contract
    already exists, returns the existing id with created_bool=False.
    """
    contract = _normalize_contract(data.get("contract") or symbol)
    with _DB_LOCK:
        with _get_connection() as conn:
            if not allow_duplicate and contract:
                row = conn.execute(
                    "SELECT id FROM trades WHERE status='ACTIVE' AND contract=? AND engine=? LIMIT 1",
                    (contract, engine)
                ).fetchone()
                if row:
                    return row["id"], False

            # Get next ID
            max_row = conn.execute("SELECT MAX(id) as m FROM trades").fetchone()
            tid = (max_row["m"] or 0) + 1
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            trade = {"id": tid, "engine": engine, "symbol": symbol, "status": "ACTIVE", "created_at": now}
            trade.update(data)
            conn.execute(
                "INSERT INTO trades (id, engine, symbol, contract, status, data_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (tid, engine, symbol, contract, trade.get("status", "ACTIVE"),
                 json.dumps(trade), now, now)
            )
    _sync_tab_databases()
    return tid, True


def update_trade(trade_id, updates):
    """Update fields on an existing trade record."""
    with _DB_LOCK:
        with _get_connection() as conn:
            row = conn.execute("SELECT data_json FROM trades WHERE id=?", (trade_id,)).fetchone()
            if not row:
                return
            trade = json.loads(row["data_json"])
            trade.update(updates)
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            trade["updated_at"] = now
            new_status = trade.get("status", "ACTIVE")
            conn.execute(
                "UPDATE trades SET data_json=?, status=?, updated_at=? WHERE id=?",
                (json.dumps(trade), new_status, now, trade_id)
            )
    _sync_tab_databases()


def update_trade_status(trade_id, status, exit_price=None, exit_reason=None, details=None, **extra):
    """Update a trade's status plus optional exit metadata.

    Missing trade_id is a silent no-op (callers guard on tid presence).
    This function is invoked by both option trade engines' KITE manual-exit
    (zero-qty) sync paths — it previously did not exist, so those calls threw
    AttributeError (silently swallowed) and closed positions stayed ACTIVE
    forever (ISSUE-052 family).
    """
    if not trade_id:
        return
    updates = {"status": status}
    if exit_price is not None:
        try:
            updates["exit_price"] = float(exit_price)
        except (TypeError, ValueError):
            pass
    if exit_reason:
        updates["exit_reason"] = exit_reason
    if details:
        updates["details"] = details
    updates.update(extra)
    updates.setdefault("exit_time", time.strftime("%Y-%m-%d %H:%M:%S"))
    update_trade(trade_id, updates)

def update_self_learning_lesson(trade_id, lesson_text):
    """Save user self-learning notes for a trade in SQLite and sync to CSV/JSON journal."""
    if not trade_id:
        return False
    with _DB_LOCK:
        with _get_connection() as conn:
            row = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
            if not row:
                row = conn.execute("SELECT * FROM trades WHERE contract=?", (str(trade_id).upper(),)).fetchone()
            if row:
                real_id = row["id"]
                data = _row_to_dict(row)
                data["self_learning_lesson"] = str(lesson_text).strip()
                data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    "UPDATE trades SET data_json=?, updated_at=? WHERE id=?",
                    (json.dumps(data), data["updated_at"], real_id)
                )
    _sync_tab_databases()
    try:
        import daily_trade_journal
        daily_trade_journal.generate_daily_journal()
    except Exception as e:
        logging.warning(f"Journal CSV sync after lesson update failed: {e}")
    return True



def find_active_trade_id(contract, engine=None):
    """Return the id of the first ACTIVE trade matching a contract, or None."""
    contract = _normalize_contract(contract)
    if not contract:
        return None
    with _get_connection() as conn:
        if engine:
            row = conn.execute(
                "SELECT id FROM trades WHERE status='ACTIVE' AND contract=? AND engine=? LIMIT 1",
                (contract, engine)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM trades WHERE status='ACTIVE' AND contract=? LIMIT 1",
                (contract,)
            ).fetchone()
    return row["id"] if row else None


def get_active_trades(engine=None):
    """Return all ACTIVE trades, optionally filtered by engine."""
    with _get_connection() as conn:
        if engine:
            rows = conn.execute(
                "SELECT * FROM trades WHERE status='ACTIVE' AND engine=?", (engine,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM trades WHERE status='ACTIVE'").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_all_trades(engine=None):
    """Return all trades, optionally filtered by engine."""
    with _get_connection() as conn:
        if engine:
            rows = conn.execute("SELECT * FROM trades WHERE engine=?", (engine,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM trades").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_completed_trades():
    """Return all non-ACTIVE trades."""
    with _get_connection() as conn:
        rows = conn.execute("SELECT * FROM trades WHERE status != 'ACTIVE'").fetchall()
    return [_row_to_dict(r) for r in rows]


def remove_trades(trade_ids):
    """Hard-delete trades by ID list."""
    if not trade_ids:
        return
    placeholders = ",".join("?" * len(trade_ids))
    with _DB_LOCK:
        with _get_connection() as conn:
            conn.execute(f"DELETE FROM trades WHERE id IN ({placeholders})", list(trade_ids))
    _sync_tab_databases()


# ════════════════════════════════════════════════════════════
#  EXPIRY / DEDUP UTILITIES
# ════════════════════════════════════════════════════════════

def _parse_embedded_expiry(contract):
    """Best-effort expiry date from contract name (YY + [M]M + DD + strike + side)."""
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
    """Remove ACTIVE trades whose contract has expired. Returns count removed."""
    today = datetime.now().date()
    active = get_active_trades()
    remove_ids = []
    for t in active:
        contract = str(t.get("contract") or t.get("symbol") or "")
        exp_date = _parse_embedded_expiry(contract)
        if exp_date is not None and exp_date < today:
            remove_ids.append(t["id"])
            continue
        if expiry_cutoff and (t.get("created_at", "")[:10] < expiry_cutoff):
            remove_ids.append(t["id"])
    if remove_ids:
        remove_trades(remove_ids)
    return len(remove_ids)


def dedupe_active_positions():
    """Collapse duplicate ACTIVE rows for the same engine+contract, keeping newest."""
    active = get_active_trades()
    seen = {}
    remove_ids = []
    for t in sorted(active, key=lambda x: x.get("created_at", ""), reverse=True):
        key = (t.get("engine"), _normalize_contract(t.get("contract") or t.get("symbol")))
        if key in seen:
            remove_ids.append(t["id"])
        else:
            seen[key] = t
    if remove_ids:
        remove_trades(remove_ids)
    return len(remove_ids)


def _parse_dt_flexible(value):
    """Parse ISO-8601 or '%Y-%m-%d %H:%M:%S' datetime strings; returns datetime or None."""
    if not value:
        return None
    s = str(value).strip().split(".")[0]
    s = s.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def reconcile_with_executed_exits(exit_orders):
    """Mark ACTIVE trades COMPLETED when a matching executed-exit order exists.

    `exit_orders` maps contract -> {"order_id":..., "timestamp":...} (the shape
    written by trading_core.save_executed_exit). A trade is only closed when the
    exit happened AFTER the row was created, so a legitimate re-entry (which
    clears the executed-exit marker) is never mis-closed. Returns count closed.
    """
    if not exit_orders:
        return 0
    by_contract = {_normalize_contract(c): e for c, e in exit_orders.items() if e}
    if not by_contract:
        return 0
    closed = 0
    for t in get_active_trades():
        contract = _normalize_contract(t.get("contract") or t.get("symbol"))
        entry = by_contract.get(contract)
        if not entry:
            continue
        exit_ts = _parse_dt_flexible(entry.get("timestamp") or entry.get("time"))
        created_ts = _parse_dt_flexible(t.get("created_at"))
        if exit_ts is not None and created_ts is not None and exit_ts < created_ts:
            continue
        try:
            update_trade_status(
                t["id"], "COMPLETED",
                exit_price=entry.get("details", {}).get("price") if isinstance(entry.get("details"), dict) else None,
                exit_reason="EXECUTED_EXIT_ORDER",
                details="Closed: executed exit order detected",
                exit_time=(exit_ts.strftime("%Y-%m-%d %H:%M:%S") if exit_ts else time.strftime("%Y-%m-%d %H:%M:%S"))
            )
        except Exception as e:
            logging.warning(f"[trade_db] reconcile exit close failed for {contract}: {e}")
            continue
        closed += 1
    return closed


def reconcile_broker_live_positions(kite):
    """Auto-reconcile DB ACTIVE trades against Kite live net positions.
    
    If an ACTIVE trade's underlying contract has net held quantity <= 0 on Kite
    and is not a pending staged entry, transition its status to COMPLETED.
    Returns count of positions reconciled.
    """
    if kite is None:
        return 0
    try:
        pos_data = kite.positions()
        net_pos = {p.get("tradingsymbol"): p for p in pos_data.get("net", []) if p.get("tradingsymbol")}
        day_pos = {p.get("tradingsymbol"): p for p in pos_data.get("day", []) if p.get("tradingsymbol")}
    except Exception as e:
        logging.warning(f"[trade_db] reconcile_broker_live_positions failed to fetch Kite positions: {e}")
        return 0

    reconciled = 0
    now_str = get_ist_now().strftime("%Y-%m-%d %H:%M:%S")
    for t in get_active_trades():
        contract = _normalize_contract(t.get("contract") or t.get("symbol"))
        if not contract:
            continue
        p_info = net_pos.get(contract) or day_pos.get(contract)
        net_qty = int(p_info.get("quantity", 0)) if p_info else 0
        if net_qty <= 0:
            logging.info(f"[trade_db] Auto-reconciling zero-qty broker position: Trade #{t['id']} {contract} (Broker Net Qty: {net_qty})")
            try:
                update_trade_status(
                    t["id"], "COMPLETED",
                    exit_price=p_info.get("sell_price") or p_info.get("last_price") if p_info else None,
                    exit_reason="BROKER_NET_QTY_ZERO_RECONCILED",
                    details="Auto-reconciled: live broker held quantity is 0",
                    exit_time=now_str
                )
                reconciled += 1
            except Exception as e:
                logging.warning(f"[trade_db] reconcile broker zero-qty close failed for #{t['id']} {contract}: {e}")

    if reconciled > 0:
        _sync_tab_databases()
    return reconciled


def run_db_housekeeping(kite=None):
    """One-shot startup cleanup: dedupe, reconcile executed exits, purge expired, reconcile broker live qty.

    Called by engine startups and dashboard refresh loops so stale ACTIVE rows
    (closed-on-Zerodha / expired contracts like NIFTY2681124650PE) can never
    linger as BUY-able ACTIVE trades. Returns a summary dict.
    """
    summary = {}
    try:
        summary["deduped"] = dedupe_active_positions()
    except Exception as e:
        logging.warning(f"[trade_db] housekeeping dedupe failed: {e}")
        summary["deduped"] = 0
    try:
        exit_orders = _read_json(paths.EXECUTED_EXITS_FILE, {})
        summary["reconciled"] = reconcile_with_executed_exits(exit_orders) if isinstance(exit_orders, dict) else 0
    except Exception as e:
        logging.warning(f"[trade_db] housekeeping reconcile failed: {e}")
        summary["reconciled"] = 0
    try:
        summary["purged"] = purge_expired_positions()
    except Exception as e:
        logging.warning(f"[trade_db] housekeeping purge failed: {e}")
        summary["purged"] = 0
    if kite is not None:
        try:
            summary["broker_reconciled"] = reconcile_broker_live_positions(kite)
        except Exception as e:
            logging.warning(f"[trade_db] housekeeping broker reconcile failed: {e}")
            summary["broker_reconciled"] = 0
    if any(summary.values()):
        logging.info(f"[trade_db] housekeeping: {summary}")
    return summary


# ════════════════════════════════════════════════════════════
#  CYCLE STAGING + EXECUTED PATTERN REGISTRY (JSON-backed)
# ════════════════════════════════════════════════════════════

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
    """True if this pattern key was already executed in a previous cycle."""
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


# ════════════════════════════════════════════════════════════
#  AUTO-INIT on import
# ════════════════════════════════════════════════════════════
_init_db()
