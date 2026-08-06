import os
import re

print("=== AUDITING ALL TARGET COMPUTATIONS IN CODEBASE ===")
for root, dirs, files in os.walk("."):
    if ".git" in root or "venv" in root:
        continue
    for f in files:
        if f.endswith(".py"):
            path = os.path.join(root, f)
            try:
                with open(path, encoding="utf-8", errors="ignore") as fh:
                    lines = fh.readlines()
                for i, line in enumerate(lines):
                    if "find_profit_targets" in line or "derive_sl_targets" in line:
                        print(f"{path}:{i+1}: {line.strip()}")
            except Exception:
                pass
