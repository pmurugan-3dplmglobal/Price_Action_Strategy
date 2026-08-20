
import urllib.request, json
req = urllib.request.urlopen('http://127.0.0.1:5050/api/status', timeout=15)
d = json.loads(req.read().decode('utf-8'))
kpos = d.get('kite_positions', [])
print(f'VM KITE POSITIONS COUNT: {len(kpos)}')
for p in kpos:
    print(f"  * {p.get('tradingsymbol') or p.get('contract')} | Qty: {p.get('quantity')} | LTP: {p.get('ltp')} | PnL: Rs. {p.get('pnl')}")
