import urllib.request
import csv
import io
import json

token = open('input/kite_access_token.txt').read().strip()
api_key = 'o8nnw6kxykvrsrhg'
headers = {
    'X-Kite-Version': '3',
    'Authorization': f'token {api_key}:{token}'
}

print("Fetching NSE instruments master...")
url = "https://api.kite.trade/instruments/NSE"
req = urllib.request.Request(url, headers=headers)
fno_symbols = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BHARTIARTL",
    "ULTRACEMCO", "BAJAJ-AUTO", "LT", "AXISBANK", "KOTAKBANK", "MARUTI",
    "ASIANPAINT", "POWERGRID", "NTPC", "TATAMOTORS", "TATASTEEL", "JSWSTEEL",
    "HINDALCO", "COALINDIA", "VEDL", "DIVISLAB", "CIPLA", "SUNPHARMA",
    "DRREDDY", "TITAN", "BAJFINANCE", "BAJAJFINSV", "NESTLEIND", "BRITANNIA",
    "HINDUNILVR", "ITC", "DLF", "GODREJPROP", "BEL", "HAL", "BHEL", "SIEMENS",
    "ABB", "VOLTAS", "POLYCAB", "KEI", "AMBER", "DIXON", "PERSISTENT",
    "COFORGE", "LTIM", "HCLTECH", "WIPRO", "TECHM", "360ONE", "LICI", "PFC",
    "RECLTD", "ADANIENT", "ADANIPORTS", "ADANIPOWER", "ATGL", "SUZLON",
    "SWIGGY", "ZOMATO", "PAYTM", "TRENT", "WAAREEENER", "PREMIERENE"
]

tokens = {}
with urllib.request.urlopen(req) as resp:
    content = resp.read().decode('utf-8')
    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        sym = row.get('tradingsymbol')
        if sym in fno_symbols:
            tokens[sym] = {
                'token': int(row.get('instrument_token')),
                'lot_size': int(row.get('lot_size', 1)),
                'tick_size': float(row.get('tick_size', 0.05))
            }

print(f"Resolved tokens for {len(tokens)} / {len(fno_symbols)} F&O symbols.")
with open('scratch/fno_tokens_master.json', 'w') as f:
    json.dump(tokens, f, indent=2)

print("Saved to scratch/fno_tokens_master.json")
