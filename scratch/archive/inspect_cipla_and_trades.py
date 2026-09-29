import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))

import sqlite3, json, csv
from common import paths, trade_db
from common.trading_core import load_kite_session
from kiteconnect import KiteConnect

print('=== Searching Trades DB (trades.sqlite3) for CIPLA ===')
conn = sqlite3.connect(trade_db._DB_PATH)
cursor = conn.cursor()
cursor.execute("SELECT id, engine, symbol, contract, status, data_json, created_at, updated_at FROM trades WHERE contract LIKE '%CIPLA%' OR symbol LIKE '%CIPLA%'")
rows = cursor.fetchall()
for r in rows:
    tid, eng, sym, cnt, st, dj, cat, uat = r
    data = json.loads(dj) if dj else {}
    print(f"ID={tid} | Eng={eng} | Sym={sym} | Cnt={cnt} | Status={st} | Created={cat}")
    print(f"   EntrySpot={data.get('entry_spot')} | EntryPrice={data.get('entry_price')} | CurrentSL={data.get('current_sl')} | T1={data.get('t1')} | PnL%={data.get('pnl_percent')} | ExitPrice={data.get('exit_price')}")
    print(f"   Details={data.get('details')} | ExitReason={data.get('exit_reason')} | ExitTime={data.get('exit_time')}")

print('\n=== All Recent Trades in DB (Today / Recent 15) ===')
cursor.execute("SELECT id, engine, symbol, contract, status, data_json, created_at FROM trades ORDER BY id DESC LIMIT 15")
for r in cursor.fetchall():
    tid, eng, sym, cnt, st, dj, cat = r
    data = json.loads(dj) if dj else {}
    print(f"ID={tid} | Sym={sym} | Cnt={cnt} | Status={st} | PnL={data.get('pnl')} ({data.get('pnl_percent')}%) | Created={cat}")
    print(f"   Entry={data.get('entry_spot') or data.get('entry_price')} | Exit={data.get('exit_price')} | Reason={data.get('details') or data.get('exit_reason')}")

print('\n=== Searching Executed Exits for CIPLA ===')
if os.path.exists(paths.EXECUTED_EXITS_FILE):
    with open(paths.EXECUTED_EXITS_FILE) as f:
        exits = json.load(f)
        for k, v in exits.items():
            if 'CIPLA' in k:
                print(k, ':', v)

print('\n=== Searching Trade Journal CSV for CIPLA ===')
if os.path.exists(paths.TRADE_JOURNAL_CSV):
    with open(paths.TRADE_JOURNAL_CSV, encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if any('CIPLA' in str(c) for c in row):
                print(row)

# Live Kite quote for CIPLA
try:
    ak, at = load_kite_session()
    kite = KiteConnect(api_key=ak)
    kite.set_access_token(at)
    quotes = kite.quote(["NSE:CIPLA", "NFO:CIPLA26OCT1400CE"])
    print("\n=== Live Kite Quotes for CIPLA ===")
    for qk, qv in quotes.items():
        ohlc = qv.get('ohlc', {})
        print(f"{qk}: LTP={qv.get('last_price')} | High={ohlc.get('high')} | Low={ohlc.get('low')} | Close={ohlc.get('close')} | Open={ohlc.get('open')} | Volume={qv.get('volume')}")
except Exception as e:
    print("Kite quote error:", e)
