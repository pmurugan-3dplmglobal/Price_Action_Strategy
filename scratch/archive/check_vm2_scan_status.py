import subprocess
import json

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

py_snippet = """
import json, os

for name, p in [
    ('scan_display.json', '/home/trade/Trade_Kite/Price_Action_Strategy/output/monitor/scan_display.json'),
    ('scan_display_index.json', '/home/trade/Trade_Kite/Price_Action_Strategy/output/monitor/scan_display_index.json'),
    ('pattern_funnel.json', '/home/trade/Trade_Kite/Price_Action_Strategy/output/monitor/pattern_funnel.json'),
]:
    if os.path.exists(p):
        try:
            d = json.load(open(p))
            if 'staged_trades' in d:
                print(f"{name}: date={d.get('date')} ts={d.get('timestamp')} staged={len(d.get('staged_trades',[]))} all_staged={len(d.get('all_staged_today',[]))} active_live={len(d.get('active_live',[]))}")
                for tr in d.get('staged_trades', []):
                    print(f"   STAGED: {tr.get('symbol')} {tr.get('contract')} side={tr.get('side')} entry={tr.get('entry_spot')} sl={tr.get('current_sl')} t1={tr.get('t1')}")
                for tr in d.get('active_live', []):
                    print(f"   ACTIVE_LIVE: {tr.get('symbol')} {tr.get('contract')} side={tr.get('side')} entry={tr.get('entry_spot')}")
            elif 'nifty50' in d:
                n = d.get('nifty50', {})
                print(f"{name} (nifty50): A+={len(n.get('category_a_plus',[]))} A={len(n.get('category_a',[]))} B={len(n.get('category_b',[]))} updated={n.get('updated_at')}")
                for it in n.get('category_a', []):
                    print(f"   [Cat A] {it.get('symbol')} {it.get('contract')} side={it.get('side')} bm={it.get('benchmark')} sl={it.get('current_sl')} t1={it.get('t1')}")
        except Exception as e:
            print(f"{name}: error {e}")
    else:
        print(f"{name}: NOT FOUND")
"""

cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@129.225.69.131",
       "/home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python -"]
res = subprocess.run(cmd, input=py_snippet, capture_output=True, text=True)
print("=== BHAVANI VM2 SCAN STATUS ===")
print(res.stdout or res.stderr)
