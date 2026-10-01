import urllib.request
import json
import datetime

token = open('input/kite_access_token.txt').read().strip()
api_key = 'o8nnw6kxykvrsrhg'
headers = {
    'X-Kite-Version': '3',
    'Authorization': f'token {api_key}:{token}'
}

# Test with token 256265 (NIFTY 50) and token 3343617 (360ONE)
instrument_token = 256265 # Nifty 50
to_date = datetime.date(2026, 10, 1)
from_date = to_date - datetime.timedelta(days=30)

url = f"https://api.kite.trade/instruments/historical/{instrument_token}/15minute?from={from_date}&to={to_date}"
print(f"Testing URL: {url}")

req = urllib.request.Request(url, headers=headers)
try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        candles = data.get('data', {}).get('candles', [])
        print(f"Success! Fetched {len(candles)} 15-minute candles over past 30 days.")
        if candles:
            print("First candle:", candles[0])
            print("Last candle:", candles[-1])
            # Count distinct trading days
            days = set(c[0][:10] for c in candles)
            print(f"Total distinct trading sessions: {len(days)}")
            print("Sessions list:", sorted(days))
except Exception as e:
    print(f"Error fetching historical data: {e}")
