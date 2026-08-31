import psutil

for p in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        cmd = ' '.join(p.info['cmdline'] or [])
        if any(w in cmd for w in ['index_options_trade_engine', 'stock_options_trade_engine', 'app_option_Trade', 'app_Stock_Trade', 'stock_bullish', 'stock_bearish']):
            print(f"PID {p.info['pid']}: {cmd[:120]}")
    except Exception:
        pass
