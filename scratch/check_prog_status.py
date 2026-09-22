import subprocess

remote_script = """
import subprocess, json

res = subprocess.run(['curl', '-s', 'http://127.0.0.1:5050/api/programs/status'], capture_output=True, text=True)
print('OPTIONS PROGRAMS STATUS:')
print(res.stdout)

res2 = subprocess.run(['curl', '-s', 'http://127.0.0.1:5051/api/programs/status'], capture_output=True, text=True)
print('STOCK PROGRAMS STATUS:')
print(res2.stdout)
"""

res = subprocess.run([
    'ssh', '-i', r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key',
    '-o', 'StrictHostKeyChecking=no',
    'opc@140.245.197.71',
    'python3'
], input=remote_script, capture_output=True, text=True)

print(res.stdout)
