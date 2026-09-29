import subprocess

remote_script = """
import os

import os, glob

import subprocess
res = subprocess.run(['ps', '-ef'], capture_output=True, text=True)
for l in res.stdout.splitlines():
    if 'python' in l:
        print(l)




"""

res = subprocess.run([
    'ssh', '-i', r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key',
    '-o', 'StrictHostKeyChecking=no',
    'opc@140.245.197.71',
    'python3'
], input=remote_script, capture_output=True, text=True)

print(res.stdout)
