import urllib.request
import json

token = open('input/kite_access_token.txt').read().strip()
api_key = 'o8nnw6kxykvrsrhg'
headers = {
    'X-Kite-Version': '3',
    'Authorization': f'token {api_key}:{token}'
}

req = urllib.request.Request('https://api.kite.trade/user/margins', headers=headers)
try:
    with urllib.request.urlopen(req) as resp:
        margins = json.loads(resp.read().decode('utf-8'))
        print("=== KITE USER MARGINS ===")
        equity = margins.get('data', {}).get('equity', {})
        for k, v in equity.items():
            print(f"{k}: {v}")
except Exception as e:
    print(f"Error fetching margins: {e}")
