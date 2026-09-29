import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

with open("scratch/log_cases_summary.txt", "r", encoding="utf-8") as f:
    text = f.read()

current_sym = None
sym_lines = {}
for line in text.splitlines():
    if line.startswith("SYMBOL: "):
        current_sym = line.split()[1]
        sym_lines[current_sym] = []
    elif current_sym:
        if "PRIORITY SCAN ORDER" not in line and not line.startswith("Interesting log lines:") and not line.startswith("==="):
            if line.strip():
                sym_lines[current_sym].append(line.strip())

for s in ["MANKIND", "VMM", "VBL", "BSE", "ADANIENT", "GLENMARK"]:
    lines = sym_lines.get(s, [])
    print(f"\n==================== {s} ({len(lines)} lines) ====================")
    for l in lines[:20]:
        print(" ", l)
    if len(lines) > 20:
        print(f"  ... ({len(lines)-30} lines hidden) ...")
        for l in lines[-10:]:
            print(" ", l)
