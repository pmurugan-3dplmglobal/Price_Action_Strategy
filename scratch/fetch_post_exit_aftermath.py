import urllib.request
import json
import datetime
import sys

sys.stdout.reconfigure(encoding='utf-8')

token = open('input/kite_access_token.txt').read().strip()
api_key = 'o8nnw6kxykvrsrhg'
headers = {
    'X-Kite-Version': '3',
    'Authorization': f'token {api_key}:{token}'
}

def get_quote(symbols):
    q_str = "&".join([f"i={urllib.parse.quote(s)}" for s in symbols])
    url = f"https://api.kite.trade/quote?{q_str}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode('utf-8'))['data']
    except Exception as e:
        print(f"Error quote: {e}")
        return {}

def fetch_candles(token_id, from_d, to_d, interval="15minute"):
    url = f"https://api.kite.trade/instruments/historical/{token_id}/{interval}?from={from_d}&to={to_d}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data.get('data', {}).get('candles', [])
    except Exception as e:
        return []

def main():
    # Let's inspect LICI 395 CE (we already fetched its 15m candles in scratch/lici_opt_candles.json)
    print("=== 1. LICI 395 CE POST-EXIT AFTERMATH ===")
    with open('scratch/lici_opt_candles.json') as f:
        lici_c = json.load(f)
    # Exited at 2026-10-01 10:17:44 @ 8.65
    post_lici = [c for c in lici_c if c[0] >= "2026-10-01T10:30:00+0530"]
    print(f"Exit Price: Rs 8.65 @ 10:17 AM")
    if post_lici:
        low_after = min(c[3] for c in post_lici)
        high_after = max(c[2] for c in post_lici)
        close_after = post_lici[-1][4]
        print(f"Post-Exit Low: Rs {low_after:.2f} (Plunged -{(8.65 - low_after)/8.65*100:.1f}% further below exit!)")
        print(f"Post-Exit High: Rs {high_after:.2f}")
        print(f"Post-Exit Close: Rs {close_after:.2f}")
        print(f"Verdict: CAPITAL SHIELD! Exiting saved an additional Rs {(8.65 - low_after) * 1400:,.2f} loss.")

    # Let's check GMR, ASTRAL, ABCAPITAL, SBIN, HDFCLIFE
    # Fetch quotes for spot stocks to get tokens
    spots = [
        "NSE:GMRAIRPORT",
        "NSE:ASTRAL",
        "NSE:ABCAPITAL",
        "NSE:SBIN",
        "NSE:HDFCLIFE",
        "NFO:GMRAIRPORT26OCT99CE",
        "NFO:ASTRAL26OCT1400CE"
    ]
    quotes = get_quote(spots)
    print("\nQuotes fetched for instruments:")
    for k, v in quotes.items():
        print(f"  {k:<24} | Token: {v.get('instrument_token')} | LTP: {v.get('last_price')} | Day Low: {v.get('ohlc',{}).get('low')} | Day High: {v.get('ohlc',{}).get('high')}")

if __name__ == '__main__':
    main()
