"""
Kite session management — token file resolution, session loading,
session refresh, safe API call wrapper, and journal logging.
Extracted from trading_core.py (2026-08-11).
"""
import os
import sys
COMMON_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(COMMON_DIR)
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import json
import logging
import csv
import time
import threading
from datetime import datetime as dt, timedelta
import paths

TOKEN_FILE = paths.TOKEN_FILE
JOURNAL_FILE = paths.TRADE_JOURNAL_CSV

# Suppress urllib3 connectionpool warnings when transient bursts occur
logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)

def get_best_token_file(default_path=TOKEN_FILE):
    base = paths.PROJECT_ROOT
    candidates = [
        default_path,
        os.path.join(base, "input", "kite_access_token.txt"),
        os.path.join(base, "Trade_Option", "input", "kite_access_token.txt"),
        os.path.join(base, "Trade_Stock", "input", "kite_access_token.txt")
    ]
    best_file = None
    best_mtime = 0
    for c in candidates:
        if os.path.exists(c):
            try:
                mtime = os.path.getmtime(c)
                if mtime > best_mtime:
                    best_mtime = mtime
                    best_file = c
            except Exception:
                pass
    return best_file or default_path

def load_kite_session(token_file=TOKEN_FILE):
    target_file = get_best_token_file(token_file)
    if not os.path.exists(target_file):
        raise FileNotFoundError(f"Token file missing at {target_file}. Run Kite_Access_Token_gen.py first.")
    with open(target_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not data.get("api_key") or not data.get("access_token"):
        raise ValueError(f"Corrupted token file at {target_file}.")
    return data["api_key"], data["access_token"]

def optimize_kite_session(kite, pool_size=50):
    """
    Mount high-capacity HTTP connection pool adapter on KiteConnect requests session.
    Prevents urllib3 'Connection pool is full, discarding connection: api.kite.trade. Connection pool size: 10'
    warnings and eliminates TCP/TLS re-handshake latency under multi-threaded concurrency.
    """
    try:
        if kite and hasattr(kite, "reqsession") and kite.reqsession:
            if not getattr(kite, "_pool_optimized", False):
                from requests.adapters import HTTPAdapter
                adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size)
                kite.reqsession.mount("https://", adapter)
                kite.reqsession.mount("http://", adapter)
                setattr(kite, "_pool_optimized", True)
                logging.debug(f"[KITE_SESSION] Mounted high-capacity HTTP connection pool (size={pool_size}) on KiteConnect session.")
    except Exception as e:
        logging.debug(f"Could not mount optimized HTTPAdapter on Kite session: {e}")


def ensure_kite_session(kite, token_file=TOKEN_FILE):
    """Ensure the KiteConnect object in memory has the latest access token from disk if it changed and has high-capacity connection pools."""
    try:
        if kite:
            optimize_kite_session(kite)
        target_file = get_best_token_file(token_file)
        if not kite or not os.path.exists(target_file):
            return
        with open(target_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        at = data.get("access_token")
        if at and getattr(kite, "access_token", None) != at:
            kite.set_access_token(at)
            logging.info(f"[KITE_SESSION] Updated in-memory KiteConnect access_token from {target_file}")
    except Exception:
        pass


def log_to_journal(symbol, pattern, timeframe, action, status, details="", pnl_pct=0.0, entry="", sl="", target="", rr="", journal_file=JOURNAL_FILE, lock=None, event_time=None):
    file_exists = os.path.exists(journal_file)
    headers = ["Timestamp", "Symbol", "Pattern", "Timeframe", "Action", "Status", "Entry", "SL", "Target", "RR", "Details", "P&L %"]
    if event_time is not None:
        raw = str(event_time).replace('T', ' ')
        if '+' in raw:
            raw = raw.split('+')[0]
        ts_str = raw
    else:
        ts_str = dt.now().strftime("%Y-%m-%d %H:%M:%S")
    row = [
        ts_str,
        symbol, pattern, timeframe, action, status,
        f"{entry:.2f}" if isinstance(entry, (int, float)) and entry else str(entry) if entry else "",
        f"{sl:.2f}" if isinstance(sl, (int, float)) and sl else str(sl) if sl else "",
        f"{target:.2f}" if isinstance(target, (int, float)) and target else str(target) if target else "",
        f"{rr:.2f}" if isinstance(rr, (int, float)) and rr else str(rr) if rr else "",
        details,
        f"{pnl_pct:.2f}%" if pnl_pct != 0.0 else "-"
    ]
    def _write():
        try:
            with open(journal_file, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, delimiter="\t")
                if not file_exists:
                    writer.writerow(headers)
                writer.writerow(row)
        except Exception as e:
            logging.error(f"Journal write failed: {e}")

    if lock:
        with lock:
            _write()
    else:
        _write()

def get_weekly_expiry(target_weekday=1):
    now = dt.now()
    days_ahead = (target_weekday - now.weekday()) % 7
    if days_ahead == 0 and now.hour >= 15:
        days_ahead = 7
    return (now + timedelta(days=days_ahead)).date()


import sqlite3


class MultiProcessTokenBucketRateLimiter:
    """Multi-process and thread-safe Token Bucket Rate Limiter to strictly comply with Zerodha Kite API rate limit (3 req/sec aggregate across processes)."""
    def __init__(self, db_path=None, rate=2.8, capacity=3.0):
        self.db_path = db_path or getattr(paths, "KITE_RATE_LIMITER_DB", os.path.join(paths.MONITOR_DIR, "kite_rate_limiter.sqlite3"))
        self.rate = rate
        self.capacity = capacity
        self.lock = threading.Lock()
        self.mem_tokens = capacity
        self.mem_last_update = time.time()
        self._init_db()

    def _init_db(self):
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=NORMAL;")
                conn.execute("CREATE TABLE IF NOT EXISTS rate_limiter (id INTEGER PRIMARY KEY, last_update REAL, tokens REAL);")
                conn.execute("INSERT OR IGNORE INTO rate_limiter (id, last_update, tokens) VALUES (1, ?, ?);", (time.time(), self.capacity))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logging.debug(f"[RATE_LIMITER] DB init error (fallback to memory): {e}")

    def acquire(self, tokens=1, priority=False):
        with self.lock:
            while True:
                now = time.time()
                wait_time = 0.05
                db_success = False
                try:
                    conn = sqlite3.connect(self.db_path, timeout=5.0)
                    conn.isolation_level = None
                    try:
                        conn.execute("BEGIN IMMEDIATE")
                        cur = conn.cursor()
                        cur.execute("SELECT last_update, tokens FROM rate_limiter WHERE id=1")
                        row = cur.fetchone()
                        if not row:
                            cur.execute("INSERT OR IGNORE INTO rate_limiter (id, last_update, tokens) VALUES (1, ?, ?)", (now, self.capacity))
                            row = (now, self.capacity)
                        last_time, curr_tokens = float(row[0]), float(row[1])
                        elapsed = max(0.0, now - last_time)
                        new_tokens = min(self.capacity, curr_tokens + elapsed * self.rate)

                        min_threshold = -1.0 if priority else 0.0
                        if (new_tokens - tokens) >= min_threshold or new_tokens >= tokens:
                            new_tokens -= tokens
                            cur.execute("UPDATE rate_limiter SET last_update=?, tokens=? WHERE id=1", (now, new_tokens))
                            conn.execute("COMMIT")
                            return
                        else:
                            needed = tokens - new_tokens
                            wait_time = max(0.01, needed / self.rate)
                            cur.execute("UPDATE rate_limiter SET last_update=?, tokens=? WHERE id=1", (now, new_tokens))
                            conn.execute("COMMIT")
                            db_success = True
                    finally:
                        conn.close()
                except Exception as err:
                    logging.debug(f"[RATE_LIMITER] Shared DB lock transient error: {err}")
                    db_success = False

                if not db_success:
                    elapsed = max(0.0, now - self.mem_last_update)
                    self.mem_last_update = now
                    self.mem_tokens = min(self.capacity, self.mem_tokens + elapsed * self.rate)
                    min_threshold = -1.0 if priority else 0.0
                    if (self.mem_tokens - tokens) >= min_threshold or self.mem_tokens >= tokens:
                        self.mem_tokens -= tokens
                        return
                    wait_time = max(0.01, (tokens - self.mem_tokens) / self.rate)

                time.sleep(min(wait_time, 0.35))


TokenBucketRateLimiter = MultiProcessTokenBucketRateLimiter
_GLOBAL_KITE_RATE_LIMITER = MultiProcessTokenBucketRateLimiter(rate=2.8, capacity=3.0)


def safe_kite_call(func, *args, retries=3, delay=0.8, priority=False, **kwargs):
    _GLOBAL_KITE_RATE_LIMITER.acquire(priority=priority)
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as err:
            err_str = str(err).lower()
            if "too many" in err_str or "requests" in err_str or "429" in err_str:
                time.sleep(delay * (attempt + 1.5))
                _GLOBAL_KITE_RATE_LIMITER.acquire(priority=priority)
            elif "access_token" in err_str or "api_key" in err_str:
                time.sleep(delay)
            else:
                raise err
    return func(*args, **kwargs)

