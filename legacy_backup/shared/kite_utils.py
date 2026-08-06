import os
import json
import time
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
                
    elapsed = time.time() - _last_hist_time
    if elapsed < 0.4:
        time.sleep(0.4 - elapsed)
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

def get_instrument_df():
    """Get the cached NFO instruments DataFrame."""
    global NFO_INSTRUMENTS
    return NFO_INSTRUMENTS