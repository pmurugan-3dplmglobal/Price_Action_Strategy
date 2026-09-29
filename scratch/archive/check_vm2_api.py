import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

py_code = """
import urllib.request, json
try:
    with urllib.request.urlopen('http://127.0.0.1:5050/api/status', timeout=5) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        progs = data.get('programs', {})
        for p, info in progs.items():
            print(f'{p}: running={info.get("running")}')
        pos = data.get('positions', [])
        print(f'Positions in API: {len(pos)}')
        for po in pos:
            print(f'  {po.get("symbol")} {po.get("contract")} pnl={po.get("pnl")}')
        sd = data.get('scan_display', {})
        print(f'scan_display nifty50 staged: {len(sd.get("nifty50", {}).get("staged_trades", []))}')
        print(f'scan_display index staged: {len(sd.get("index", {}).get("staged_trades", []))}')
except Exception as e:
    print('API error:', e)
"""

cmd = ['ssh', '-i', KEY, '-o', 'StrictHostKeyChecking=no', 'opc@129.225.69.131',
       '/home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python -']
res = subprocess.run(cmd, input=py_code, capture_output=True, text=True)
print(res.stdout or res.stderr)
