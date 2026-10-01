import urllib.request
import json

token = open('input/kite_access_token.txt').read().strip()
api_key = 'o8nnw6kxykvrsrhg'
headers = {'X-Kite-Version': '3', 'Authorization': f'token {api_key}:{token}'}

def get(path):
    try:
        req = urllib.request.Request(f'https://api.kite.trade{path}', headers=headers)
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        return {'error': str(e)}

print("=== CHECKING KITE ENDPOINTS ===")
endpoints = [
    '/orders/trades',
    '/portfolio/positions',
    '/portfolio/holdings',
]

for ep in endpoints:
    res = get(ep)
    if 'data' in res:
        data = res['data']
        if isinstance(data, list):
            print(f"{ep}: {len(data)} items")
            for item in data[:3]:
                print("  ", item)
        elif isinstance(data, dict):
            print(f"{ep}: keys {list(data.keys())}")
            for k, v in data.items():
                if isinstance(v, list):
                    print(f"   {k}: {len(v)} items")
    else:
        print(f"{ep}: error -> {res}")
