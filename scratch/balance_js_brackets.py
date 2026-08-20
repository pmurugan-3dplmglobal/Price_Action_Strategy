with open("Trade_Stock/app_Stock_Trade.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

in_script = False
depth = 0
for idx, line in enumerate(lines, 1):
    if "<script>" in line and not in_script:
        in_script = True
        depth = 0
        continue
    if "</script>" in line and in_script:
        break

    if in_script:
        old_depth = depth
        for ch in line:
            if ch == '{': depth += 1
            elif ch == '}': depth -= 1
        # If line changed depth unexpectedly or at function boundary
        if "function " in line or depth < 0 or (old_depth == 0 and depth > 0 and "function" not in line and "class" not in line and "const" not in line and "let" not in line and "var" not in line):
            print(f"Line {idx:4d} (depth {old_depth} -> {depth}): {line.strip()[:80]}")

print(f"Total lines checked. Final depth: {depth}")
