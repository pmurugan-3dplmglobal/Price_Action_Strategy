import subprocess
import json

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

py_snippet = """
import json, os

for name, p in [
    ('scan_display.json', 'output/monitor/scan_display.json'),
    ('scan_display_index.json', 'output/monitor/scan_display_index.json'),
    ('pattern_funnel.json', 'output/monitor/pattern_funnel.json'),
]:
    if os.path.exists(p):
        try:
            d = json.load(open(p))
            if 'staged_trades' in d:
                print(f"  {name}: date={d.get('date')} staged={len(d.get('staged_trades',[]))} active_live={len(d.get('active_live',[]))}")
                for tr in d.get('staged_trades', []):
                    print(f"     STAGED: {tr.get('symbol')} {tr.get('contract')} side={tr.get('side')} entry={tr.get('entry_spot')} sl={tr.get('current_sl')} t1={tr.get('t1')}")
            elif 'nifty50' in d:
                n = d.get('nifty50', {})
                print(f"  {name} (nifty50): A+={len(n.get('category_a_plus',[]))} A={len(n.get('category_a',[]))} B={len(n.get('category_b',[]))}")
        except Exception as e:
            print(f"  {name}: error {e}")
"""

def inspect(vm_name, host, venv_py, base_dir):
    print(f"=== {vm_name} ({host}) ===")
    cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", host, f"cd {base_dir} && {venv_py} -"]
    res = subprocess.run(cmd, input=py_snippet, capture_output=True, text=True)
    print(res.stdout or res.stderr)

if __name__ == "__main__":
    inspect("Bhavani VM2", "opc@129.225.69.131", "/home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python", "/home/trade/Trade_Kite/Price_Action_Strategy")
    inspect("Poovendan VM1", "opc@140.245.197.71", "/home/opc/Price_Action_Strategy/venv/bin/python", "/home/opc/Price_Action_Strategy")
