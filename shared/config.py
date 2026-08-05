import os
import json

CFG_FILE = os.path.join("input", "program_config.json")

def load_program_config():
    with open(CFG_FILE, "r") as f:
        return json.load(f)

_config = load_program_config()

LIVE_MARKET_DEPLOYMENT = False
BACKTEST_DATE = None
LOOKBACK_DAYS = 30
INITIAL_CAPITAL = 100000.0
MAX_RISK_PERCENT = 1.0

TIMEFRAME_ENTRY = "3minute"
TIMEFRAME_ANCHOR = "15minute"
TIMEFRAME_FALLBACK = "3minute"

STRIKE_RANGE = 1

API_KEY = _config.get("api_key", "")
API_SECRET = _config.get("api_secret", "")
TOKEN_FILE = "input/kite_access_token.txt"

INDEX_CONFIG = _config.get("index", {})
NIFTY50_CONFIG = _config.get("nifty50", {})
BEAR_INDEX_CONFIG = _config.get("bear_index", {})
BEAR_NIFTY50_CONFIG = _config.get("bear_nifty50", {})
DAILY_CONFIG = _config.get("daily", {})

INDEX_TF_FALLBACK = "3minute"
INDEX_TF_ENTRY = INDEX_CONFIG.get("timeframe", "3minute")
INDEX_TF_ANCHOR = INDEX_CONFIG.get("timeframe_anchor", "10minute")
INDEX_LOOKBACK = INDEX_CONFIG.get("lookback_days", 100)
INDEX_SCAN_INTERVAL = INDEX_CONFIG.get("scan_interval", 15)
INDEX_RISK_PCT = INDEX_CONFIG.get("risk_percent", 1)
INDEX_CAPITAL = INDEX_CONFIG.get("capital", 100000)
INDEX_STRIKE_RANGE = INDEX_CONFIG.get("strike_range", 2)

NIFTY50_TF_FALLBACK = "15minute"
NIFTY50_TF_ENTRY = NIFTY50_CONFIG.get("timeframe", "15minute")
NIFTY50_TF_ANCHOR = NIFTY50_CONFIG.get("timeframe_anchor", "30minute")
NIFTY50_LOOKBACK = NIFTY50_CONFIG.get("lookback_days", 200)
NIFTY50_SCAN_INTERVAL = NIFTY50_CONFIG.get("scan_interval", 30)
NIFTY50_RISK_PCT = NIFTY50_CONFIG.get("risk_percent", 10)
NIFTY50_CAPITAL = NIFTY50_CONFIG.get("capital", 100000)
NIFTY50_STRIKE_RANGE = NIFTY50_CONFIG.get("strike_range", 1)

BEAR_INDEX_TF_ENTRY = BEAR_INDEX_CONFIG.get("timeframe", "3minute")
BEAR_INDEX_TF_ANCHOR = BEAR_INDEX_CONFIG.get("timeframe_anchor", "10minute")
BEAR_INDEX_LOOKBACK = BEAR_INDEX_CONFIG.get("lookback_days", 30)
BEAR_INDEX_SCAN_INTERVAL = BEAR_INDEX_CONFIG.get("scan_interval", 15)
BEAR_INDEX_RISK_PCT = BEAR_INDEX_CONFIG.get("risk_percent", 1)
BEAR_INDEX_CAPITAL = BEAR_INDEX_CONFIG.get("capital", 100000)
BEAR_INDEX_STRIKE_RANGE = BEAR_INDEX_CONFIG.get("strike_range", 3)

BEAR_NIFTY50_TF_ENTRY = BEAR_NIFTY50_CONFIG.get("timeframe", "15minute")
BEAR_NIFTY50_TF_ANCHOR = BEAR_NIFTY50_CONFIG.get("timeframe_anchor", "30minute")
BEAR_NIFTY50_LOOKBACK = BEAR_NIFTY50_CONFIG.get("lookback_days", 30)
BEAR_NIFTY50_SCAN_INTERVAL = BEAR_NIFTY50_CONFIG.get("scan_interval", 300)
BEAR_NIFTY50_RISK_PCT = BEAR_NIFTY50_CONFIG.get("risk_percent", 1)
BEAR_NIFTY50_CAPITAL = BEAR_NIFTY50_CONFIG.get("capital", 100000)
BEAR_NIFTY50_STRIKE_RANGE = BEAR_NIFTY50_CONFIG.get("strike_range", 1)

DAILY_TF = DAILY_CONFIG.get("timeframe", "day")
DAILY_LOOKBACK = DAILY_CONFIG.get("lookback_days", 500)

VALID_TIMEFRAMES = {"minute", "3minute", "5minute", "10minute", "15minute", "30minute", "60minute", "4hour", "day"}

SCAN_INTERVAL_SECONDS = 15

INDEX_REGISTRY = {
    "NIFTY": {"token": 256265, "lot_size": 65, "strike_step": 50, "tradingsymbol": "NIFTY 50"},
    "BANKNIFTY": {"token": 260105, "lot_size": 30, "strike_step": 100, "tradingsymbol": "NIFTY BANK"},
}

STOCK_REGISTRY = {
    "ADANIENT": {"token": 257801, "lot_size": 1700, "strike_step": 50},
    "ADANIPORTS": {"token": 1510401, "lot_size": 1250, "strike_step": 20},
    "APOLLOHOSP": {"token": 1723649, "lot_size": 300, "strike_step": 50},
    "ASIANPAINT": {"token": 60417, "lot_size": 300, "strike_step": 50},
    "AXISBANK": {"token": 1510401, "lot_size": 625, "strike_step": 10},
    "BAJAJ-AUTO": {"token": 2097153, "lot_size": 125, "strike_step": 100},
    "BAJFINANCE": {"token": 1667585, "lot_size": 125, "strike_step": 100},
    "BAJAJFINSV": {"token": 4268545, "lot_size": 500, "strike_step": 20},
    "BAJFINANCE": {"token": 81153, "lot_size": 125, "strike_step": 100},
    "BEL": {"token": 54017, "lot_size": 1000, "strike_step": 5},
    "BHARTIARTL": {"token": 2714625, "lot_size": 950, "strike_step": 20},
    "CIPLA": {"token": 177665, "lot_size": 650, "strike_step": 20},
    "COALINDIA": {"token": 5215745, "lot_size": 1250, "strike_step": 10},
    "DRREDDY": {"token": 225537, "lot_size": 125, "strike_step": 100},
    "EICHERMOT": {"token": 232961, "lot_size": 175, "strike_step": 50},
    "GRASIM": {"token": 315393, "lot_size": 400, "strike_step": 20},
    "HCLTECH": {"token": 1837313, "lot_size": 700, "strike_step": 20},
    "HDFCBANK": {"token": 341249, "lot_size": 550, "strike_step": 10},
    "HDFCLIFE": {"token": 119553, "lot_size": 1100, "strike_step": 10},
    "HEROMOTOCO": {"token": 345089, "lot_size": 300, "strike_step": 50},
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
    "NESTLEIND": {"token": 4543233, "lot_size": 400, "strike_step": 20},
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
    "TCS": {"token": 2953217, "lot_size": 175, "strike_step": 50},
    "TECHM": {"token": 3418369, "lot_size": 600, "strike_step": 20},
    "TITAN": {"token": 895745, "lot_size": 375, "strike_step": 50},
    "TRENT": {"token": 5064961, "lot_size": 150, "strike_step": 100},
    "ULTRACEMCO": {"token": 2952193, "lot_size": 100, "strike_step": 100},
    "WIPRO": {"token": 969473, "lot_size": 1500, "strike_step": 5},
}

SUPER_STOCKS = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY",
    "ITC", "SBIN", "BHARTIARTL", "LT", "WIPRO"
]

ANCHOR_SCAN_REQUEST_FILE = os.path.join("output", "monitor", "anchor_scan_request.txt")
ANCHOR_SCAN_STOP_FILE = os.path.join("output", "monitor", "anchor_scan_stop.txt")
SCANNER_CONFIG_FILE = os.path.join("output", "monitor", "scanner_config.json")
JOURNAL_FILE = os.path.join("output", "monitor", "trade_journal.csv")
TRADES_DB_FILE = os.path.join("output", "monitor", "trades_db.json")
EXECUTED_PATTERNS_FILE = os.path.join("output", "monitor", "executed_patterns.json")
CYCLE_TRADES_FILE = os.path.join("output", "monitor", "cycle_trades.json")
STOCK_POSITIONS_FILE = os.path.join("output", "monitor", "stock_positions_state.json")
BEAR_STOCK_POSITIONS_FILE = os.path.join("output", "monitor", "bear_stock_positions_state.json")
EXPORT_STATE_FILE = os.path.join("output", "monitor", "export_state.json")