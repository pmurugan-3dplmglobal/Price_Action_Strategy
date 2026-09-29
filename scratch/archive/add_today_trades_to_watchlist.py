import sys
import os
import json

sys.path.insert(0, 'common')
sys.path.insert(0, 'Trade_Option')

from trading_core import load_kite_session
from kiteconnect import KiteConnect
from watchlist_monitor import add_watchlist_item, fetch_watchlist_live_data, load_watchlist_config
import paths

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

today_trades = [
    {
        "contract": "APLAPOLLO26SEP2200PE",
        "base_symbol": "APLAPOLLO",
        "entry_price": 30.00,
        "exit_price": 43.75,
        "lot_size": 350,
        "tag": "POST_PROFIT_RUN",
        "note": "Booked +45.8% Profit (+Rs 4,812) @ 43.75 peak | Watching post-exit consolidation"
    },
    {
        "contract": "BAJAJFINSV26SEP1860PE",
        "base_symbol": "BAJAJFINSV",
        "entry_price": 22.60,
        "exit_price": 39.00,
        "lot_size": 300,
        "tag": "POST_PROFIT_RUN",
        "note": "Booked +72.6% Profit (+Rs 4,920) @ 39.00 | Massive intraday breakdown runner"
    },
    {
        "contract": "WIPRO26SEP160CE",
        "base_symbol": "WIPRO",
        "entry_price": 4.50,
        "exit_price": 5.41,
        "lot_size": 3000,
        "tag": "POST_PROFIT_RUN",
        "note": "Booked +20.2% Profit (+Rs 2,730) @ 5.41 | Watching continuation momentum"
    },
    {
        "contract": "NIFTY2692223450PE",
        "base_symbol": "NIFTY",
        "entry_price": 48.45,
        "exit_price": 90.30,
        "lot_size": 65,
        "tag": "POST_PROFIT_RUN",
        "note": "Booked +86.4% Profit (+Rs 2,720) @ 90.30 | 0DTE Expiry trend collapse runner"
    },
    {
        "contract": "INFY26SEP1020CE",
        "base_symbol": "INFY",
        "entry_price": 18.00,
        "exit_price": 20.00,
        "lot_size": 400,
        "tag": "POST_PROFIT_RUN",
        "note": "Booked +11.1% Profit (+Rs 800) @ 20.00 | Watching retest of 1020 breakout level"
    },
    {
        "contract": "APLAPOLLO26SEP2180PE",
        "base_symbol": "APLAPOLLO",
        "entry_price": 23.15,
        "exit_price": 25.00,
        "lot_size": 350,
        "tag": "POST_PROFIT_RUN",
        "note": "Booked +8.0% Profit (+Rs 647) @ 25.00 | Lower-strike hedge/runner"
    },
    {
        "contract": "GODREJPROP26SEP1700CE",
        "base_symbol": "GODREJPROP",
        "entry_price": 36.50,
        "exit_price": 37.55,
        "lot_size": 325,
        "tag": "POST_PROFIT_RUN",
        "note": "Capital Preserved (+Rs 341) @ 37.55 | Successfully exited before plunge to 27.75"
    },
    {
        "contract": "ASIANPAINT26SEP2460CE",
        "base_symbol": "ASIANPAINT",
        "entry_price": 21.15,
        "exit_price": None,
        "lot_size": 250,
        "tag": "ACTIVE_MONITOR",
        "note": "Active Call Option @ 21.15 | Holding structural anchor support"
    },
    {
        "contract": "NAUKRI26SEP1300PE",
        "base_symbol": "NAUKRI",
        "entry_price": 14.80,
        "exit_price": None,
        "lot_size": 550,
        "tag": "ACTIVE_MONITOR",
        "note": "Active Bear Put Spread Long Leg @ 14.80 | Strike 1300 PE"
    },
    {
        "contract": "NAUKRI26SEP1260PE",
        "base_symbol": "NAUKRI",
        "entry_price": 3.15,
        "exit_price": None,
        "lot_size": 550,
        "tag": "ACTIVE_MONITOR",
        "note": "Active Bear Put Spread Short Leg @ 3.15 | Strike 1260 PE (Hedge)"
    },
    {
        "contract": "JSWENERGY26SEP520CE",
        "base_symbol": "JSWENERGY",
        "entry_price": 6.60,
        "exit_price": 4.90,
        "lot_size": 1075,
        "tag": "POST_EXIT_LEARNING",
        "note": "Booked SL @ 4.90 (-Rs 1,827) | Watching post-exit recovery & spot 516 support"
    },
    {
        "contract": "CANBK26SEP125CE",
        "base_symbol": "CANBK",
        "entry_price": 1.17,
        "exit_price": 0.83,
        "lot_size": 6750,
        "tag": "POST_EXIT_LEARNING",
        "note": "Unwound Unhedged Leg @ 0.83 (-Rs 2,295) | Watching 122.5 support reaction"
    }
]

print(f"Adding {len(today_trades)} traded scripts to Watchlist...")
for t in today_trades:
    add_watchlist_item(
        contract=t["contract"],
        base_symbol=t["base_symbol"],
        entry_price=t["entry_price"],
        exit_price=t["exit_price"],
        lot_size=t["lot_size"],
        tag=t["tag"],
        note=t["note"]
    )

print("\nFetching live quotes and generating output/monitor/watchlist_live.json...")
live_results = fetch_watchlist_live_data(kite)
print(f"[SUCCESS] Updated watchlist_live.json with {len(live_results)} monitored items!")

for r in live_results:
    c = r.get("contract")
    tag = r.get("tag")
    ltp = r.get("opt_ltp")
    verdict = r.get("verdict")
    print(f"  {c:<25} | Tag: {tag:<18} | LTP: {ltp:<6.2f} | {verdict}")
