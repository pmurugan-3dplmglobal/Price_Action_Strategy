import subprocess

remote_script = """
import subprocess

ps = subprocess.run(['pgrep', '-a', 'python'], capture_output=True, text=True).stdout
print('=== ALL PYTHON PROCESSES ON VM ===')
print(ps)
"""

res = subprocess.run([
    'ssh', '-i', r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key',
    '-o', 'StrictHostKeyChecking=no',
    'opc@140.245.197.71',
    'python3'
], input=remote_script, capture_output=True, text=True)

print(res.stdout)
