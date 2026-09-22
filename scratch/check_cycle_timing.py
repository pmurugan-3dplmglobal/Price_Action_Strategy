import subprocess
res = subprocess.run(['ssh', '-i', r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key', '-o', 'StrictHostKeyChecking=no', 'opc@140.245.197.71', 'journalctl -u trading-options -n 15 --no-pager'], capture_output=True, text=True)
print(res.stdout)
