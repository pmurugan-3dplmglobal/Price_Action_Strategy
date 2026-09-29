import subprocess

remote_script = """
import os

os.system('grep -rn "74700" /home/opc/Price_Action_Strategy/output/ 2>/dev/null | grep -E "\\.csv|\\.json|\\.log"')
"""

res = subprocess.run([
    'ssh', '-i', r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key',
    '-o', 'StrictHostKeyChecking=no',
    'opc@140.245.197.71',
    'python3'
], input=remote_script, capture_output=True, text=True)

print(res.stdout)
if res.stderr:
    print("STDERR:", res.stderr)
