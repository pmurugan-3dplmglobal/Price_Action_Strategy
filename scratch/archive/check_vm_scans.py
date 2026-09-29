import subprocess

KEY = r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key'
VMS = [
    ('VM1 (Poovendan)', '140.245.197.71', 'opc', '/home/opc/Price_Action_Strategy'),
    ('VM2 (Bhavani)', '129.225.69.131', 'opc', '/home/trade/Trade_Kite/Price_Action_Strategy')
]

REMOTE_SCRIPT = """
import json, glob

for f in sorted(glob.glob('output/monitor/scan_display*.json')):
    try:
        d = json.load(open(f))
        staged = d.get('staged_trades', [])
        all_staged = d.get('all_staged_today', [])
        print(f"File: {f} | staged: {len(staged)} | all_staged: {len(all_staged)}")
        for t in staged:
            cnt = t.get('contract')
            sym = t.get('symbol')
            print(f"  [STAGED] {sym} | {cnt} | BM={t.get('benchmark')} | SL={t.get('current_sl')} | T1={t.get('t1')} | StagedT={t.get('staged_time')}")
    except Exception as e:
        print(f"Error {f}: {e}")
"""

for name, ip, user, dir_ in VMS:
    print(f"\n{'='*70}\n{name} ({ip})\n{'='*70}")
    ssh_cmd = [
        'ssh', '-i', KEY,
        '-o', 'StrictHostKeyChecking=no',
        f"{user}@{ip}",
        f"cd {dir_} && python3 -"
    ]
    res = subprocess.run(ssh_cmd, input=REMOTE_SCRIPT, capture_output=True, text=True)
    print(res.stdout)
    if res.stderr and 'Permanently added' not in res.stderr:
        print("STDERR:", res.stderr)
