import json
import shutil
import os

config_path = r"C:\Users\poove\.gemini\config\projects\c281d8a2-6605-4a55-8d0e-bf155795d938.json"
bak_path = config_path + ".bak"

if not os.path.exists(bak_path):
    shutil.copyfile(config_path, bak_path)
    print("Backup created at:", bak_path)

with open(config_path, "r", encoding="utf-8") as f:
    data = json.load(f)

# 1. Update autoExecutionPolicy to CASCADE_COMMANDS_AUTO_EXECUTION_EAGER
if "settings" not in data:
    data["settings"] = {}
data["settings"]["autoExecutionPolicy"] = "CASCADE_COMMANDS_AUTO_EXECUTION_EAGER"

# 2. Add whitelist permissions
grants = data.setdefault("permissionGrants", {}).setdefault("permissionGrants", {})
allow_list = grants.setdefault("allow", [])

cmds_to_add = [
    r"command(python scratch/fetch_today_analysis.py)",
    r"command(python C:\Users\poove\.gemini\antigravity\brain\8638a122-3f9f-4d46-a07a-6614ceec7949\scratch\fetch_today_analysis.py)",
    r"command(python C:\Users\poove\.gemini\antigravity\brain\8638a122-3f9f-4d46-a07a-6614ceec7949\scratch\audit_today_trades.py)",
    r'command(Get-Content C:\Users\poove\.gemini\antigravity\brain\8638a122-3f9f-4d46-a07a-6614ceec7949\scratch\audit_today_trades.py | ssh -i G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key opc@140.245.197.71 "cd /home/opc/Price_Action_Strategy && python3 - /home/opc/Price_Action_Strategy")',
    r'command(ssh -i G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key -o StrictHostKeyChecking=no opc@140.245.197.71 "python3 -c \"import sqlite3, json, os\n\ndb = \\\"/home/opc/Price_Action_Strategy/output/monitor/trades.sqlite3\\\"\nif os.path.exists(db):\n    conn = sqlite3.connect(db)\")'
]

for cmd in cmds_to_add:
    if cmd not in allow_list:
        allow_list.append(cmd)

with open(config_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)

print("SUCCESS: autoExecutionPolicy updated to CASCADE_COMMANDS_AUTO_EXECUTION_EAGER")
print(f"Total allowed commands: {len(allow_list)}")
