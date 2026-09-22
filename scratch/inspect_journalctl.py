import subprocess

remote_script = """
import subprocess

cmd = ['sudo', 'journalctl', '-u', 'trading-options', '-u', 'trading-stock', '-n', '50', '--no-pager']
res = subprocess.run(cmd, capture_output=True, text=True)
print(res.stdout)
if res.stderr:
    print('STDERR:', res.stderr)
"""

res = subprocess.run([
    'ssh', '-i', r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key',
    '-o', 'StrictHostKeyChecking=no',
    'opc@140.245.197.71',
    'python3'
], input=remote_script, capture_output=True, text=True)

print(res.stdout)
