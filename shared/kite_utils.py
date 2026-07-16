import os
import json
import time
import random
import logging
import pandas as pd
from datetime import datetime as dt, timedelta
from kiteconnect import KiteConnect

from shared.config import TOKEN_FILE, API_KEY, API_SECRET

_last_hist_time = 0
_instruments_lock = None
NFO_INSTRUMENTS = pd.DataFrame()
instrument_dump = None

STOCK_REGISTRY = {}
SUPER_STOCKS = []
INDEX_REGISTRY = {}

def init_registries(stock_registry, super_stocks, index_registry):
    """Initialize registries from config module (called once at startup)."""
    global STOCK_REGISTRY, SUPER_STOCKS, INDEX_REGISTRY
    STOCK_REGISTRY = stock_registry
    SUPER_STOCKS = super_stocks
    INDEX_REGISTRY = index_registry

def load_kite_session():
    if not os.path.exists(TOKEN_FILE):
        raise FileNotFoundError("Token file missing. Run Kite_Access_Token_gen.py first.")
    with open(TOKEN_FILE) as f:
        data = json.load(f)
    if not data.get("api_key") or not data.get("access_token"):
        raise ValueError("Corrupted token file.")
    return data["api_key"], data["access_token"]

def create_kite_client():
    api_key, access_token = load_kite_session()
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    return kite

def is_market_hours():
    now = dt.now()
    if now.weekday() in [5, 6]:
        return False
    t = now.time()
    from datetime import time as datetime_time
    return datetime_time(9, 15) <= t <= datetime_time(15, 30)

def is_auth_error(e):
    """True if the Kite exception is an auth/token rejection. Kite invalidates the
    previous session's token every time a new login/access-token is generated, so a
    long-running engine can suddenly start getting 'invalid token' until it reloads."""
    msg = str(e).lower()
    return any(k in msg for k in (
        "invalid token", "invalid access token", "token exception",
        "unauthorized", "not authenticated", "expired", "403", "invalid request token"
    ))

def reload_kite_client(kite=None):
    """Recreate the Kite client from the current token file and re-sync instruments.
    Call when Kite reports an auth/token error so the engine self-heals after a
    token regeneration (Kite invalidates the previous session on each new login)."""
    new_kite = create_kite_client()
    try:
        fetch_instruments(new_kite)
    except Exception as e:
        logging.warning(f"Instrument re-sync failed during token reload: {e}")
    return new_kite


def validate_stock_registry_tokens(kite, stock_registry=None):
    """Cross-check STOCK_REGISTRY equity tokens against live NSE EQ instruments and
    self-correct stale/wrong tokens in place (mutates shared.config.STOCK_REGISTRY).
    Cheap relative to a scan: a single NSE instruments() call. Returns a list of
    (symbol, old_token, new_token) corrections. Call once at engine startup (and on
    token reload) so a de-listed/renamed/rotated equity token can never silently
    break an entire scan cycle again."""
    import shared.config as _cfg
    registry = stock_registry if stock_registry is not None else _cfg.STOCK_REGISTRY
    if not registry:
        return []
    try:
        eq = kite.instruments("NSE")
    except Exception as e:
        logging.warning(f"validate_stock_registry_tokens: NSE instrument fetch failed: {e}")
        return []
    live = {}
    for r in eq:
        if r.get("instrument_type") == "EQ":
            live[str(r["tradingsymbol"]).upper()] = int(r["instrument_token"])
    corrections = []
    for sym, meta in list(registry.items()):
        tok = live.get(sym.upper())
        if tok is None:
            logging.warning(
                f"validate_stock_registry_tokens: {sym} not found on NSE EQ; "
                f"keeping token {meta.get('token')}"
            )
            continue
        if int(meta.get("token", 0)) != tok:
            old = meta.get("token")
            meta["token"] = tok
            corrections.append((sym, old, tok))
            logging.warning(f"validate_stock_registry_tokens: corrected {sym} token {old} -> {tok}")
    if corrections:
        logging.info(f"validate_stock_registry_tokens: {len(corrections)} token(s) corrected.")
    return corrections


CACHE_DIR = os.path.join("output", "cache")

def safe_historical(kite, token, from_date, to_date, tf, max_retries=5):
    """kite.historical_data with rate limit (~2.5 req/s), retry on 429, and disk cache for past data."""
    global _last_hist_time
    
    # We only cache if we are querying past historical data (to_date is in the past)
    from datetime import date
    today = date.today()
    query_to_date = None
    
    if isinstance(to_date, str):
        try:
            query_to_date = dt.strptime(to_date.split()[0], "%Y-%m-%d").date()
        except:
            pass
    elif isinstance(to_date, dt):
        query_to_date = to_date.date()
    elif isinstance(to_date, date):
        query_to_date = to_date
        
    is_historical_only = query_to_date is not None and query_to_date < today
    cache_file = None
    
    if is_historical_only:
        os.makedirs(CACHE_DIR, exist_ok=True)
        from_str = from_date.strftime("%Y-%m-%d") if hasattr(from_date, "strftime") else str(from_date)
        to_str = to_date.strftime("%Y-%m-%d") if hasattr(to_date, "strftime") else str(to_date)
        # Clean filename representing query parameters
        cache_name = f"hist_{token}_{from_str}_{to_str}_{tf}.json"
        cache_file = os.path.join(CACHE_DIR, cache_name)
        
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                    # Convert ISO date strings back to timezone-aware datetime objects
                    for item in cached_data:
                        if 'date' in item and isinstance(item['date'], str):
                            date_str = item['date'].replace('Z', '+00:00')
                            item['date'] = dt.fromisoformat(date_str)
                    return cached_data
            except Exception as e:
                logging.warning(f"Error reading historical cache for token {token}: {e}")
                
    # Per-process pacing to avoid Kite 429s; jitter desynchronizes the 4 engines
    MIN_GAP = 0.75
    elapsed = time.time() - _last_hist_time
    if elapsed < MIN_GAP:
        time.sleep(MIN_GAP - elapsed + random.uniform(0, 0.15))
    _last_hist_time = time.time()
    
    for attempt in range(max_retries):
        try:
            data = kite.historical_data(token, from_date, to_date, tf)
            
            if is_historical_only and data and cache_file:
                try:
                    # Serialize datetime objects to ISO strings for JSON storage
                    serializable_data = []
                    for item in data:
                        serialized_item = item.copy()
                        if 'date' in serialized_item and isinstance(serialized_item['date'], dt):
                            serialized_item['date'] = serialized_item['date'].isoformat()
                        serializable_data.append(serialized_item)
                        
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump(serializable_data, f, indent=2)
                except Exception as e:
                    logging.warning(f"Error writing historical cache for token {token}: {e}")
            return data
        except Exception as e:
            msg = str(e).lower()
            if "too many requests" in msg and attempt < max_retries - 1:
                wait = 2 ** attempt
                logging.warning(f"429 on hist data (token={token} tf={tf}) — retry {attempt+1}/{max_retries} after {wait}s")
                time.sleep(wait)
            else:
                raise
    return []


def fetch_instruments(kite):
    """Sync NFO instruments from Kite."""
    global instrument_dump, NFO_INSTRUMENTS
    try:
        logging.info("Syncing NFO instruments...")
        instruments = kite.instruments("NFO")
        instrument_dump = pd.DataFrame(instruments)
        NFO_INSTRUMENTS = instrument_dump.copy()
        logging.info(f"Synced {len(NFO_INSTRUMENTS)} NFO contracts.")
    except Exception as e:
        logging.error(f"Instrument sync failed: {e}")
        raise

def sync_instruments(kite):
    return fetch_instruments(kite)


def resolve_futures_token(base_symbol):
    """Resolve current-month NFO futures token for a stock/index base symbol."""
    global NFO_INSTRUMENTS, instrument_dump
    df = NFO_INSTRUMENTS if not NFO_INSTRUMENTS.empty else (instrument_dump if instrument_dump is not None else pd.DataFrame())
    if df.empty:
        return None
    futs = df[df['instrument_type'] == 'FUT']
    if futs.empty:
        return None
    # Build a mapping: name -> list of (tradingsymbol, token, expiry)
    # Pick the nearest expiry (current month)
    from datetime import date
    today = date.today()
    best = None
    for _, r in futs.iterrows():
        if str(r['name']).upper() == base_symbol.upper():
            expiry = r.get('expiry')
            if expiry is not None:
                if best is None or abs((expiry - today).days) < abs((best[1] - today).days):
                    best = (int(r['instrument_token']), expiry if hasattr(expiry, 'date') else expiry)
    if best is None:
        return None
    return best[0]


def get_instrument_df():
    """Get the cached NFO instruments DataFrame."""
    global NFO_INSTRUMENTS
    return NFO_INSTRUMENTS