"""
Symbol registries — STOCK_REGISTRY, INDEX_REGISTRY, SUPER_STOCKS, and sync_stock_tokens.
Extracted from trading_core.py (2026-08-11).
"""
import logging
import pandas as pd
import paths

SUPER_STOCKS = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY",
    "ITC", "SBIN", "BHARTIARTL", "LT", "WIPRO"
]

def match_registry_symbol(registry, tradingsymbol):
    """Return the registry key that best matches a tradingsymbol, longest-match first.

    Fixes the mislabel bug where 'NIFTY' matched inside 'BANKNIFTY26AUG57700PE'
    before 'BANKNIFTY' was checked (dict iteration order is insertion order).
    Returns None when nothing matches.
    """
    if not registry or not tradingsymbol:
        return None
    raw = str(tradingsymbol).replace(" ", "").upper()
    for sym in sorted(registry.keys(), key=len, reverse=True):
        if sym.replace(" ", "").upper() in raw:
            return sym
    return None

STOCK_REGISTRY = {
    "ADANIENT": {"token": 112129, "lot_size": 250, "strike_step": 50},
    "ADANIPORTS": {"token": 3861249, "lot_size": 400, "strike_step": 20},
    "APOLLOHOSP": {"token": 415745, "lot_size": 125, "strike_step": 100},
    "ASIANPAINT": {"token": 60417, "lot_size": 200, "strike_step": 20},
    "AXISBANK": {"token": 1510401, "lot_size": 625, "strike_step": 10},
    "BAJAJ-AUTO": {"token": 4267777, "lot_size": 125, "strike_step": 100},
    "BAJAJFINSV": {"token": 4268545, "lot_size": 500, "strike_step": 20},
    "BAJFINANCE": {"token": 81153, "lot_size": 125, "strike_step": 100},
    "BEL": {"token": 54017, "lot_size": 1000, "strike_step": 5},
    "BHARTIARTL": {"token": 2714625, "lot_size": 950, "strike_step": 20},
    "CIPLA": {"token": 177665, "lot_size": 650, "strike_step": 20},
    "COALINDIA": {"token": 5215745, "lot_size": 1250, "strike_step": 10},
    "DRREDDY": {"token": 225537, "lot_size": 625, "strike_step": 20},
    "EICHERMOT": {"token": 232961, "lot_size": 175, "strike_step": 50},
    "ETERNAL": {"token": 1304833, "lot_size": 2425, "strike_step": 5},
    "GRASIM": {"token": 315393, "lot_size": 400, "strike_step": 20},
    "HCLTECH": {"token": 1837313, "lot_size": 700, "strike_step": 20},
    "HDFCBANK": {"token": 341249, "lot_size": 550, "strike_step": 10},
    "HDFCLIFE": {"token": 119553, "lot_size": 1100, "strike_step": 10},
    "HINDALCO": {"token": 348417, "lot_size": 1400, "strike_step": 10},
    "HINDUNILVR": {"token": 3404801, "lot_size": 300, "strike_step": 20},
    "ICICIBANK": {"token": 1270529, "lot_size": 700, "strike_step": 10},
    "INDIGO": {"token": 2865921, "lot_size": 300, "strike_step": 50},
    "INFY": {"token": 408065, "lot_size": 400, "strike_step": 20},
    "ITC": {"token": 424961, "lot_size": 1600, "strike_step": 5},
    "JIOFIN": {"token": 21806081, "lot_size": 2000, "strike_step": 5},
    "JSWSTEEL": {"token": 3001857, "lot_size": 675, "strike_step": 10},
    "KOTAKBANK": {"token": 492033, "lot_size": 400, "strike_step": 20},
    "LT": {"token": 2939649, "lot_size": 300, "strike_step": 50},
    "M&M": {"token": 519937, "lot_size": 350, "strike_step": 20},
    "MARUTI": {"token": 2800641, "lot_size": 50, "strike_step": 100},
    "MAXHEALTH": {"token": 5728513, "lot_size": 525, "strike_step": 10},
    "NESTLEIND": {"token": 4543233, "lot_size": 500, "strike_step": 20},
    "NTPC": {"token": 2977281, "lot_size": 3000, "strike_step": 5},
    "ONGC": {"token": 633601, "lot_size": 3850, "strike_step": 5},
    "POWERGRID": {"token": 3834113, "lot_size": 3600, "strike_step": 5},
    "RELIANCE": {"token": 738561, "lot_size": 250, "strike_step": 20},
    "SBILIFE": {"token": 5633, "lot_size": 750, "strike_step": 20},
    "SBIN": {"token": 7795201, "lot_size": 1500, "strike_step": 10},
    "SHRIRAMFIN": {"token": 3184129, "lot_size": 300, "strike_step": 20},
    "SUNPHARMA": {"token": 857857, "lot_size": 700, "strike_step": 20},
    "TATACONSUM": {"token": 3465729, "lot_size": 550, "strike_step": 20},
    "TATASTEEL": {"token": 897537, "lot_size": 5500, "strike_step": 2},
    "TMPV": {"token": 884737, "lot_size": 1600, "strike_step": 10},
    "TCS": {"token": 2953217, "lot_size": 175, "strike_step": 50},
    "TECHM": {"token": 3418369, "lot_size": 600, "strike_step": 20},
    "TITAN": {"token": 895745, "lot_size": 375, "strike_step": 50},
    "TRENT": {"token": 5064961, "lot_size": 150, "strike_step": 100},
    "ULTRACEMCO": {"token": 2952193, "lot_size": 100, "strike_step": 100},
    "VEDL": {"token": 0, "lot_size": 1000, "strike_step": 5},
    "WIPRO": {"token": 969473, "lot_size": 1500, "strike_step": 5}
}

def sync_stock_tokens(kite):
    try:
        instruments = kite.instruments("NSE")
        df = pd.DataFrame(instruments)
        if not df.empty:
            df['tradingsymbol'] = df['tradingsymbol'].str.strip()
            df['segment'] = df['segment'].str.strip()
            synced = 0
            for sym in STOCK_REGISTRY:
                m = df[(df['tradingsymbol'] == sym) & (df['segment'] == 'NSE')]
                if not m.empty:
                    STOCK_REGISTRY[sym]["token"] = int(m.iloc[0]['instrument_token'])
                    synced += 1
            logging.info(f"Synced tokens for {synced} stocks")
    except Exception as e:
        logging.error(f"Stock token sync failed: {e}")

# ──────────────────────────────────────────────
#  SESSION & UTILITIES
# ──────────────────────────────────────────────

INDEX_REGISTRY = {
    "NIFTY": {"token": 256265, "lot_size": 65, "strike_step": 50, "tradingsymbol": "NIFTY 50", "exchange": "NFO"},
    "BANKNIFTY": {"token": 260105, "lot_size": 30, "strike_step": 100, "tradingsymbol": "NIFTY BANK", "exchange": "NFO"},
    "SENSEX": {"token": 265, "lot_size": 20, "strike_step": 100, "tradingsymbol": "BSE SENSEX", "exchange": "BFO"}
}
