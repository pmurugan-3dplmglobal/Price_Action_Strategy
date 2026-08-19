"""
Kite session management — token file resolution, session loading,
session refresh, safe API call wrapper, and journal logging.
Extracted from trading_core.py (2026-08-11).
"""
import os
import json
import logging
import csv
import time
import threading
from datetime import datetime as dt, timedelta
import paths

TOKEN_FILE = paths.TOKEN_FILE
JOURNAL_FILE = paths.TRADE_JOURNAL_CSV

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

def ensure_kite_session(kite, token_file=TOKEN_FILE):
    """Ensure the KiteConnect object in memory has the latest access token from disk if it changed."""
    try:
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


class TokenBucketRateLimiter:
    """Thread-safe Token Bucket Rate Limiter to comply with Zerodha Kite API rate limit (3 req/sec)."""
    def __init__(self, rate=2.8, capacity=3.0):
        self.rate = rate          # Tokens added per second (e.g. 2.8 req/sec)
        self.capacity = capacity  # Maximum bucket capacity
        self.tokens = capacity
        self.last_update = time.time()
        self.lock = threading.Lock()

    def acquire(self, tokens=1):
        with self.lock:
            while True:
                now = time.time()
                elapsed = now - self.last_update
                self.last_update = now
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return
                # Need to wait
                needed = tokens - self.tokens
                wait_time = needed / self.rate
                time.sleep(max(0.01, wait_time))

_GLOBAL_KITE_RATE_LIMITER = TokenBucketRateLimiter(rate=2.8, capacity=3.0)


def safe_kite_call(func, *args, retries=3, delay=0.8, **kwargs):
    _GLOBAL_KITE_RATE_LIMITER.acquire()
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as err:
            err_str = str(err).lower()
            if "too many" in err_str or "requests" in err_str or "429" in err_str:
                time.sleep(delay * (attempt + 1.5))
                _GLOBAL_KITE_RATE_LIMITER.acquire()
            elif "access_token" in err_str or "api_key" in err_str:
                time.sleep(delay)
            else:
                raise err
    return func(*args, **kwargs)

