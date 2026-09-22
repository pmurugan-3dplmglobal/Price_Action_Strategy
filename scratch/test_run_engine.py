import subprocess

cmd = """
/home/opc/Price_Action_Strategy/venv/bin/python /home/opc/Price_Action_Strategy/Trade_Option/stock_options_trade_engine.py
"""

res = subprocess.run([
    'ssh', '-i', r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key',
    '-o', 'StrictHostKeyChecking=no',
    'opc@140.245.197.71',
    'timeout 10 /home/opc/Price_Action_Strategy/venv/bin/python /home/opc/Price_Action_Strategy/Trade_Option/stock_options_trade_engine.py'
], capture_output=True, text=True)

print("RETURNCODE:", res.returncode)
print("STDOUT:\n", res.stdout)
print("STDERR:\n", res.stderr)
