"""
Symbol registries — STOCK_REGISTRY, INDEX_REGISTRY, SUPER_STOCKS, and sync_stock_tokens.
Extracted from trading_core.py (2026-08-11).
"""
import logging
import pandas as pd
import paths

INDEX_REGISTRY = {
    "NIFTY": {"token": 256265, "lot_size": 65, "strike_step": 50, "tradingsymbol": "NIFTY 50", "exchange": "NFO"},
    "BANKNIFTY": {"token": 260105, "lot_size": 30, "strike_step": 100, "tradingsymbol": "NIFTY BANK", "exchange": "NFO"},
    "SENSEX": {"token": 265, "lot_size": 20, "strike_step": 100, "tradingsymbol": "BSE SENSEX", "exchange": "BFO"},
    "MIDCPNIFTY": {"token": 288009, "lot_size": 120, "strike_step": 25, "tradingsymbol": "NIFTY MID SELECT", "exchange": "NFO"},
    "FINNIFTY": {"token": 257801, "lot_size": 65, "strike_step": 50, "tradingsymbol": "NIFTY FIN SERVICE", "exchange": "NFO"}
}

SUPER_STOCKS = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY",
    "ITC", "SBIN", "BHARTIARTL", "LT", "WIPRO"
]

def extract_underlying_symbol(tradingsymbol):
    """Extract underlying symbol from a tradingsymbol (e.g. KAYNES26SEP3900PE -> KAYNES, NIFTY26AUG24000CE -> NIFTY)."""
    if not tradingsymbol:
        return None
    raw = str(tradingsymbol).strip().upper()
    for reg in (INDEX_REGISTRY, STOCK_REGISTRY):
        for sym in sorted(reg.keys(), key=len, reverse=True):
            if sym.replace(" ", "").upper() in raw:
                return sym
    import re
    m = re.match(r"^([A-Z&-]+?)\d{2}[A-Z]{3}", raw)
    if m:
        return m.group(1)
    return raw

def match_registry_symbol(registry, tradingsymbol):
    """Return the registry key that best matches a tradingsymbol, longest-match first.

    Fixes the mislabel bug where 'NIFTY' matched inside 'BANKNIFTY26AUG57700PE'
    before 'BANKNIFTY' was checked (dict iteration order is insertion order).
    Falls back to extract_underlying_symbol if direct substring match is missing.
    Returns None when nothing matches.
    """
    if not registry or not tradingsymbol:
        return None
    raw = str(tradingsymbol).replace(" ", "").upper()
    for sym in sorted(registry.keys(), key=len, reverse=True):
        if sym.replace(" ", "").upper() in raw:
            return sym
    extracted = extract_underlying_symbol(tradingsymbol)
    if extracted and extracted in registry:
        return extracted
    return None

STOCK_REGISTRY = {
    "ADANIENT": {"token": 6401, "lot_size": 250, "strike_step": 50},
    "ADANIPORTS": {"token": 3861249, "lot_size": 400, "strike_step": 20},
    "APOLLOHOSP": {"token": 40193, "lot_size": 125, "strike_step": 100},
    "ASIANPAINT": {"token": 60417, "lot_size": 200, "strike_step": 20},
    "AXISBANK": {"token": 1510401, "lot_size": 625, "strike_step": 10},
    "BAJAJ-AUTO": {"token": 4267265, "lot_size": 125, "strike_step": 100},
    "BAJAJFINSV": {"token": 4268801, "lot_size": 500, "strike_step": 20},
    "BAJFINANCE": {"token": 81153, "lot_size": 125, "strike_step": 100},
    "BEL": {"token": 98049, "lot_size": 1000, "strike_step": 5},
    "BHARTIARTL": {"token": 2714625, "lot_size": 950, "strike_step": 20},
    "CIPLA": {"token": 177665, "lot_size": 650, "strike_step": 20},
    "COALINDIA": {"token": 5215745, "lot_size": 1250, "strike_step": 10},
    "DRREDDY": {"token": 225537, "lot_size": 625, "strike_step": 20},
    "EICHERMOT": {"token": 232961, "lot_size": 175, "strike_step": 50},
    "ETERNAL": {"token": 1304833, "lot_size": 2425, "strike_step": 5},
    "GRASIM": {"token": 315393, "lot_size": 400, "strike_step": 20},
    "HCLTECH": {"token": 1850625, "lot_size": 700, "strike_step": 20},
    "HDFCBANK": {"token": 341249, "lot_size": 550, "strike_step": 10},
    "HDFCLIFE": {"token": 119553, "lot_size": 1100, "strike_step": 10},
    "HINDALCO": {"token": 348929, "lot_size": 1400, "strike_step": 10},
    "HINDUNILVR": {"token": 356865, "lot_size": 300, "strike_step": 20},
    "ICICIBANK": {"token": 1270529, "lot_size": 700, "strike_step": 10},
    "INDIGO": {"token": 2865921, "lot_size": 300, "strike_step": 50},
    "INFY": {"token": 408065, "lot_size": 400, "strike_step": 20},
    "ITC": {"token": 424961, "lot_size": 1600, "strike_step": 5},
    "JIOFIN": {"token": 4644609, "lot_size": 2000, "strike_step": 5},
    "JSWSTEEL": {"token": 3001089, "lot_size": 675, "strike_step": 10},
    "KOTAKBANK": {"token": 492033, "lot_size": 400, "strike_step": 20},
    "LT": {"token": 2939649, "lot_size": 300, "strike_step": 50},
    "LTIM": {"token": 4571905, "lot_size": 150, "strike_step": 50},
    "M&M": {"token": 519937, "lot_size": 350, "strike_step": 20},
    "MARUTI": {"token": 2815745, "lot_size": 50, "strike_step": 100},
    "MAXHEALTH": {"token": 5728513, "lot_size": 525, "strike_step": 10},
    "NESTLEIND": {"token": 4598529, "lot_size": 500, "strike_step": 20},
    "NTPC": {"token": 2977281, "lot_size": 3000, "strike_step": 5},
    "ONGC": {"token": 633601, "lot_size": 3850, "strike_step": 5},
    "POWERGRID": {"token": 3834113, "lot_size": 3600, "strike_step": 5},
    "RELIANCE": {"token": 738561, "lot_size": 250, "strike_step": 20},
    "SBILIFE": {"token": 5582849, "lot_size": 750, "strike_step": 20},
    "SBIN": {"token": 779521, "lot_size": 1500, "strike_step": 10},
    "SHRIRAMFIN": {"token": 1102337, "lot_size": 300, "strike_step": 20},
    "SUNPHARMA": {"token": 857857, "lot_size": 700, "strike_step": 20},
    "TATACONSUM": {"token": 878593, "lot_size": 550, "strike_step": 20},
    "TATAMOTORS": {"token": 884737, "lot_size": 1425, "strike_step": 10},
    "TATASTEEL": {"token": 895745, "lot_size": 5500, "strike_step": 2},
    "TCS": {"token": 2953217, "lot_size": 175, "strike_step": 50},
    "TECHM": {"token": 3465729, "lot_size": 600, "strike_step": 20},
    "TITAN": {"token": 897537, "lot_size": 375, "strike_step": 50},
    "TMPV": {"token": 884737, "lot_size": 1600, "strike_step": 10},
    "TRENT": {"token": 502785, "lot_size": 150, "strike_step": 100},
    "ULTRACEMCO": {"token": 2952193, "lot_size": 100, "strike_step": 100},
    "WIPRO": {"token": 969473, "lot_size": 1500, "strike_step": 5}
}

def _populate_stock_registry_from_cache():
    """Populate full F&O stock registry dynamically from NFO cache CSV on disk."""
    try:
        import os
        if os.path.exists(paths.NFO_CACHE_FILE):
            df = pd.read_csv(paths.NFO_CACHE_FILE)
            if not df.empty and 'name' in df.columns:
                options = df[df['segment'] == 'NFO-OPT'] if 'segment' in df.columns else df
                index_names = {'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX', 'BANKEX', 'NIFTYNXT50'}
                for name, group in options.groupby('name'):
                    sym = str(name).strip().upper()
                    if sym in index_names:
                        continue
                    lot = int(group.iloc[0]['lot_size']) if 'lot_size' in group.columns else 1
                    tok = int(group.iloc[0]['instrument_token']) if 'instrument_token' in group.columns else 0
                    strikes = sorted(group['strike'].dropna().unique()) if 'strike' in group.columns else []
                    if len(strikes) >= 2:
                        diffs = [round(float(strikes[i+1] - strikes[i]), 2) for i in range(min(10, len(strikes)-1)) if strikes[i+1] > strikes[i]]
                        step = float(min(diffs)) if diffs else 10.0
                    else:
                        step = 10.0
                    if sym not in STOCK_REGISTRY:
                        STOCK_REGISTRY[sym] = {"token": tok, "lot_size": lot, "strike_step": step}
                    else:
                        if tok > 0 and STOCK_REGISTRY[sym].get("token", 0) == 0:
                            STOCK_REGISTRY[sym]["token"] = tok
                        STOCK_REGISTRY[sym]["lot_size"] = lot
                        if "strike_step" not in STOCK_REGISTRY[sym] or not STOCK_REGISTRY[sym]["strike_step"]:
                            STOCK_REGISTRY[sym]["strike_step"] = step
    except Exception as e:
        logging.debug(f"Failed to populate STOCK_REGISTRY from NFO cache: {e}")

_populate_stock_registry_from_cache()

def sync_stock_tokens(kite):
    try:
        instruments = kite.instruments("NSE")
        df = pd.DataFrame(instruments)
        if not df.empty:
            df['tradingsymbol'] = df['tradingsymbol'].str.strip()
            df['segment'] = df['segment'].str.strip()
            nse_df = df[df['segment'] == 'NSE']
            nse_map = dict(zip(nse_df['tradingsymbol'], nse_df['instrument_token']))
            synced = 0
            for sym in list(STOCK_REGISTRY.keys()):
                # Direct match or hyphen-normalized match (e.g. BAJAJ-AUTO vs BAJAJ_AUTO)
                tok = nse_map.get(sym) or nse_map.get(sym.replace("_", "-")) or nse_map.get(sym.replace("-", ""))
                if tok:
                    STOCK_REGISTRY[sym]["token"] = int(tok)
                    synced += 1
            logging.info(f"Synced tokens for {synced} stocks from NSE instrument master")
    except Exception as e:
        logging.error(f"Stock token sync failed: {e}")
    return STOCK_REGISTRY

def sync_fno_stock_registry(kite, target_universe="FNO_ALL"):
    """
    Dynamically discover all NSE F&O underlying equities from NFO instrument master,
    resolve tokens from NSE instrument master, calculate exact strike steps & lot sizes,
    and populate STOCK_REGISTRY.
    """
    try:
        logging.info("Syncing full NSE F&O stock registry from Kite Connect...")
        nfo = kite.instruments("NFO")
        df_nfo = pd.DataFrame(nfo)
        if df_nfo.empty:
            return STOCK_REGISTRY

        options = df_nfo[df_nfo['segment'] == 'NFO-OPT']
        if options.empty:
            return STOCK_REGISTRY

        nse = kite.instruments("NSE")
        df_nse = pd.DataFrame(nse)
        if df_nse.empty:
            return STOCK_REGISTRY

        df_nse = df_nse[df_nse['segment'] == 'NSE']
        nse_token_map = dict(zip(df_nse['tradingsymbol'].str.strip(), df_nse['instrument_token']))

        index_names = {'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX', 'BANKEX', 'NIFTYNXT50'}
        added_count = 0

        for name, group in options.groupby('name'):
            sym = str(name).strip().upper()
            if sym in index_names:
                continue
            tok = int(nse_token_map.get(sym, 0))
            if tok == 0:
                continue
            lot = int(group.iloc[0]['lot_size'])
            strikes = sorted(group['strike'].dropna().unique())
            if len(strikes) >= 2:
                diffs = [round(float(strikes[i+1] - strikes[i]), 2) for i in range(min(10, len(strikes)-1)) if strikes[i+1] > strikes[i]]
                step = float(min(diffs)) if diffs else 10.0
            else:
                step = 10.0

            if sym not in STOCK_REGISTRY:
                STOCK_REGISTRY[sym] = {"token": tok, "lot_size": lot, "strike_step": step}
                added_count += 1
            else:
                STOCK_REGISTRY[sym]["token"] = tok
                STOCK_REGISTRY[sym]["lot_size"] = lot
                if "strike_step" not in STOCK_REGISTRY[sym] or not STOCK_REGISTRY[sym]["strike_step"]:
                    STOCK_REGISTRY[sym]["strike_step"] = step

        logging.info(f"F&O stock registry synchronized: {len(STOCK_REGISTRY)} active F&O equities ({added_count} newly added).")
        return STOCK_REGISTRY
    except Exception as e:
        logging.error(f"F&O stock registry sync failed: {e}")
        return STOCK_REGISTRY

