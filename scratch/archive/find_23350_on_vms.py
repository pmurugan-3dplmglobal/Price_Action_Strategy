import subprocess

KEY = r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key'
VMS = [
    ('VM1 (Poovendan)', '140.245.197.71', 'opc', '/home/opc/Price_Action_Strategy'),
    ('VM2 (Bhavani)', '129.225.69.131', 'opc', '/home/trade/Trade_Kite/Price_Action_Strategy')
]

REMOTE_SCRIPT = """
import os, glob

target = "23350"
for root, dirs, files in os.walk("output"):
    for f in files:
        if f.endswith((".json", ".csv", ".sqlite3")):
            p = os.path.join(root, f)
            try:
                content = open(p, "rb").read()
                if target.encode() in content:
                    print(f"Found {target} in {p} (size={len(content)})")
            except Exception:
                pass
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
