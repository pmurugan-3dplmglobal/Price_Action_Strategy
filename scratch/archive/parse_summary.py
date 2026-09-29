import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

with open("scratch/log_cases_summary.txt", "r", encoding="utf-8") as f:
    text = f.read()

sections = text.split("==========================================")
for sec in sections:
    if not sec.strip():
        continue
    lines = sec.strip().split("\n")
    header = lines[0]
    print("\n" + "=" * 60)
    print(">>> " + header)
    print("=" * 60)
    for l in lines[1:]:
        if "PRIORITY SCAN ORDER" in l:
            continue
        print(l)
