import json
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

with open("scratch/scanned_setups_detailed_audit.json", "r", encoding="utf-8") as f:
    data = json.load(f)

multibaggers = [d for d in data if d.get("max_gain_pct", 0) >= 50.0]
print(f"Total Multibagger Setups (>= 50%): {len(multibaggers)}")
print("-" * 95)
print(f"{'Symbol':12s} | {'Contract':22s} | {'Pattern':14s} | {'Tier':10s} | {'BM':7s} | {'High':7s} | {'Gain':8s}")
print("-" * 95)

tier_counts = {}
for m in sorted(multibaggers, key=lambda x: x["max_gain_pct"], reverse=True):
    tier = m.get("tier", "Unknown")
    tier_counts[tier] = tier_counts.get(tier, 0) + 1
    print(f"{m['symbol']:12s} | {m['contract']:22s} | {m['pattern']:14s} | {tier:10s} | {m['benchmark']:7.2f} | {m['day_high']:7.2f} | +{m['max_gain_pct']:.1f}%")

print("-" * 95)
print("Tier Distribution of >50% Multibagger Setups:")
for t, cnt in tier_counts.items():
    print(f"  {t}: {cnt} setups ({cnt/len(multibaggers)*100:.1f}%)")

