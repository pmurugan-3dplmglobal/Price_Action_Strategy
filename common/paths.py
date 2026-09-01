import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directory for temporary scratch files (validation artifacts, etc.)
SCRATCH_DIR = os.path.join(PROJECT_ROOT, "scratch")


# Canonical directory paths
INPUT_DIR = os.path.join(PROJECT_ROOT, "input")
MONITOR_DIR = os.path.join(PROJECT_ROOT, "output", "monitor")
LOGS_DIR = os.path.join(PROJECT_ROOT, "output", "logs")
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "output", "exports")


def input_file(name):
    return os.path.join(INPUT_DIR, name)


def monitor_file(name):
    return os.path.join(MONITOR_DIR, name)


def log_file(name):
    return os.path.join(LOGS_DIR, name)


def export_file(name):
    return os.path.join(EXPORTS_DIR, name)


# Shared canonical paths (single source of truth for cross-module files)
TOKEN_FILE = input_file("kite_access_token.txt")
NFO_CACHE_FILE = monitor_file("nfo_instruments_cache.csv")
SL_TARGET_OVERRIDES_FILE = monitor_file("sl_target_overrides.json")
EXECUTED_EXITS_FILE = monitor_file("executed_exit_orders.json")
JOURNAL_TRADES_DB = monitor_file("journal_trades_db.json")
TRADE_JOURNAL_CSV = monitor_file("trade_journal.csv")
PROGRAM_CONFIG_FILE = input_file("program_config.json")
WATCHLIST_CONFIG_FILE = input_file("watchlist.json")
WATCHLIST_LIVE_FILE = monitor_file("watchlist_live.json")
DASHBOARD_USERS_FILE = monitor_file("dashboard_users.json")
DASHBOARD_SECRET_KEY_FILE = input_file("dashboard_secret_key.txt")
EXPORT_STATE_FILE = monitor_file("export_state.json")
TRADE_ARCHIVE_XLSX = export_file("trade_archive.xlsx")

# Trade databases (what engines + dashboards read/write)
TRADES_DB = monitor_file("trades_db.json")
ACTIVE_POSITIONS_DB = monitor_file("active_positions_db.json")
SCANNED_TRADES_DB = monitor_file("scanned_trades_db.json")
CYCLE_STORE_FILE = monitor_file("cycle_trades.json")
EXECUTED_STORE_FILE = monitor_file("executed_patterns.json")

# Scan display files (what the dashboards read)
SCAN_DISPLAY_FILE = monitor_file("scan_display.json")
SCAN_DISPLAY_INDEX_FILE = monitor_file("scan_display_index.json")
SCAN_DISPLAY_STOCK_FILE = monitor_file("scan_display_stock.json")
SCAN_DISPLAY_BEAR_FILE = monitor_file("scan_display_stock_bear.json")
SCAN_DISPLAY_WEEKLY_FILE = monitor_file("scan_display_stock_weekly.json")
SCAN_DISPLAY_WEEKLY_BEAR_FILE = monitor_file("scan_display_stock_weekly_bear.json")
SCAN_DISPLAY_EMA_FILE = monitor_file("scan_display_ema.json")
SCAN_DISPLAY_EMA_STOCK_FILE = monitor_file("scan_display_ema_stock.json")

# Log files (what the dashboards tail)
NIFTY50_LOG_FILE = log_file("bull_nifty50_scanner.log")
INDEX_LOG_FILE = log_file("bull_index_trade_engine.log")
EMA_LOG_FILE = log_file("ema_engine.log")
BULL_DAILY_SCAN_LOG = log_file("bull_daily_scanner.log")
BEAR_DAILY_SCAN_LOG = log_file("bull_bear_daily_scanner.log")
WEEKLY_BULL_SCAN_LOG = log_file("bull_weekly_scanner.log")
WEEKLY_BEAR_SCAN_LOG = log_file("bull_weekly_bear_scanner.log")

# Live execution flags
NIFTY50_LIVE_FLAG = input_file("nifty50_live.flag")
INDEX_LIVE_FLAG = input_file("index_live.flag")
