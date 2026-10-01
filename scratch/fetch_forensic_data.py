import urllib.request
import json
import os
import sys

token = open('input/kite_access_token.txt').read().strip()
api_key = 'o8nnw6kxykvrsrhg'

headers = {
    'X-Kite-Version': '3',
    'Authorization': f'token {api_key}:{token}'
}

# 1. Fetch quotes
symbols = [
    'NFO:360ONE26OCT1040CE',
    'NSE:360ONE',
    'NFO:ULTRACEMCO26OCT10900PE',
    'NSE:ULTRACEMCO',
    'NFO:LICI26OCT395CE',
    'NSE:LICI',
    'NSE:NIFTY 50',
    'NFO:NIFTY26O0622300CE',
    'NFO:NIFTY26O0622500CE'
]

query_str = "&".join([f"i={urllib.parse.quote(s)}" for s in symbols])
req = urllib.request.Request(f'https://api.kite.trade/quote?{query_str}', headers=headers)
try:
    with urllib.request.urlopen(req) as resp:
        quotes = json.loads(resp.read().decode('utf-8'))['data']
except Exception as e:
    print(f"Error fetching quotes: {e}")
    sys.exit(1)

with open('scratch/forensic_quotes.json', 'w', encoding='utf-8') as f:
    json.dump(quotes, f, indent=2)

print("Quotes fetched successfully:")
tokens = {}
for k, v in quotes.items():
    tok = v.get('instrument_token')
    tokens[k] = tok
    ltp = v.get('last_price')
    ohlc = v.get('ohlc', {})
    print(f"{k:28} | Token: {tok:8} | LTP: {ltp:8.2f} | Open: {ohlc.get('open')} | High: {ohlc.get('high')} | Low: {ohlc.get('low')} | Close: {ohlc.get('close')}")

# 2. Fetch 15-minute historical candles for 360ONE Option and Spot
def fetch_candles(token, tf="15minute", days=4):
    from datetime import datetime, timedelta
    to_d = datetime.now().strftime("%Y-%m-%d")
    from_d = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    url = f"https://api.kite.trade/instruments/historical/{token}/{tf}?from={from_d}&to={to_d}"
    r = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(r) as resp:
            return json.loads(resp.read().decode('utf-8'))['data']['candles']
    except Exception as ce:
        print(f"Candle error for {token}: {ce}")
        return []

# Save 360ONE Option candles
opt_tok = tokens.get('NFO:360ONE26OCT1040CE')
spot_tok = tokens.get('NSE:360ONE')

if opt_tok:
    candles_opt = fetch_candles(opt_tok, "15minute")
    with open('scratch/360one_opt_candles.json', 'w', encoding='utf-8') as f:
        json.dump(candles_opt, f, indent=2)
    print(f"\nFetched {len(candles_opt)} 15m candles for 360ONE 1040 CE")

if spot_tok:
    candles_spot = fetch_candles(spot_tok, "15minute")
    with open('scratch/360one_spot_candles.json', 'w', encoding='utf-8') as f:
        json.dump(candles_spot, f, indent=2)
    print(f"Fetched {len(candles_spot)} 15m candles for 360ONE Spot")

# Save ULTRACEMCO candles
u_opt_tok = tokens.get('NFO:ULTRACEMCO26OCT10900PE')
u_spot_tok = tokens.get('NSE:ULTRACEMCO')
if u_opt_tok:
    u_candles = fetch_candles(u_opt_tok, "15minute")
    with open('scratch/ultracemco_opt_candles.json', 'w', encoding='utf-8') as f:
        json.dump(u_candles, f, indent=2)
    print(f"Fetched {len(u_candles)} 15m candles for ULTRACEMCO 10900 PE")

# Save LICI candles
l_opt_tok = tokens.get('NFO:LICI26OCT395CE')
l_spot_tok = tokens.get('NSE:LICI')
if l_opt_tok:
    l_candles = fetch_candles(l_opt_tok, "15minute")
    with open('scratch/lici_opt_candles.json', 'w', encoding='utf-8') as f:
        json.dump(l_candles, f, indent=2)
    print(f"Fetched {len(l_candles)} 15m candles for LICI 395 CE")
