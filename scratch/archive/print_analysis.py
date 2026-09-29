import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

with open("scratch/scanned_setups_analysis.json", "r", encoding="utf-8") as f:
    data = json.load(f)

print("=" * 80)
print(f"1. 🎯 FULL T1 REACHED ({len(data['t1_hit'])} Setups)")
print("=" * 80)
for i, item in enumerate(data['t1_hit'], 1):
    gain_high = ((item['high'] - item['entry']) / item['entry'] * 100) if item['entry'] else 0
    curr_gain = ((item['ltp'] - item['entry']) / item['entry'] * 100) if item['entry'] else 0
    print(f" {i}. {item['symbol']} - {item['contract']} ({item['side']}) [{item['pattern']}]")
    print(f"    Entry: {item['entry']:.2f} | SL: {item['sl']:.2f} | 0.8T1: {item['t1_80']:.2f} | Target 1: {item['t1']:.2f}")
    print(f"    Today High: {item['high']:.2f} (+{gain_high:.1f}%) | Low: {item['low']:.2f} | Current LTP: {item['ltp']:.2f} ({curr_gain:+.1f}%)")
    print(f"    Staged Time: {item.get('staged_time') or '-'} | Entry Candle: {item.get('entry_time') or '-'}")
    print("-" * 80)

print("\n" + "=" * 80)
print(f"2. 🏃 0.8 T1 REACHED / RUNAWAY ({len(data['runaway_08_t1'])} Setups - Reached >= 80% to T1)")
print("=" * 80)
for i, item in enumerate(data['runaway_08_t1'], 1):
    gain_high = ((item['high'] - item['entry']) / item['entry'] * 100) if item['entry'] else 0
    curr_gain = ((item['ltp'] - item['entry']) / item['entry'] * 100) if item['entry'] else 0
    print(f" {i}. {item['symbol']} - {item['contract']} ({item['side']}) [{item['pattern']}]")
    print(f"    Entry: {item['entry']:.2f} | SL: {item['sl']:.2f} | 0.8T1: {item['t1_80']:.2f} | Target 1: {item['t1']:.2f}")
    print(f"    Today High: {item['high']:.2f} (+{gain_high:.1f}%) | Low: {item['low']:.2f} | Current LTP: {item['ltp']:.2f} ({curr_gain:+.1f}%)")
    print(f"    Staged Time: {item.get('staged_time') or '-'} | Entry Candle: {item.get('entry_time') or '-'}")
    print("-" * 80)

print("\n" + "=" * 80)
print(f"3. 🛑 STOP-LOSS (SL) HIT ({len(data['sl_hit'])} Setups)")
print("=" * 80)
# Group SL hits by how deep they fell
sl_breached = []
for item in data['sl_hit']:
    sl_breached.append(item)

# Sort by biggest drop
sl_breached.sort(key=lambda x: (x['low'] - x['sl']) / x['sl'] if x['sl'] else 0)

for i, item in enumerate(sl_breached[:15], 1):
    drop_pct = ((item['low'] - item['entry']) / item['entry'] * 100) if item['entry'] else 0
    curr_pnl = ((item['ltp'] - item['entry']) / item['entry'] * 100) if item['entry'] else 0
    print(f" {i:2d}. {item['symbol']} - {item['contract']} ({item['side']}) | Entry: {item['entry']:.2f} | SL: {item['sl']:.2f} | Low: {item['low']:.2f} | LTP: {item['ltp']:.2f} ({curr_pnl:+.1f}%)")

print(f" ... and {len(sl_breached) - 15} more SL-hit setups.")

print("\n" + "=" * 80)
print(f"4. 🟢 STILL ACTIVE / FRESH IN RISK CORRIDOR ({len(data['active_valid'])} Setups)")
print("=" * 80)
for i, item in enumerate(data['active_valid'][:15], 1):
    curr_pnl = ((item['ltp'] - item['entry']) / item['entry'] * 100) if item['entry'] else 0
    dist_to_t1_80 = ((item['t1_80'] - item['ltp']) / item['entry'] * 100) if item['entry'] else 0
    print(f" {i:2d}. {item['symbol']} - {item['contract']} ({item['side']}) | Entry: {item['entry']:.2f} | SL: {item['sl']:.2f} | 0.8T1: {item['t1_80']:.2f} | LTP: {item['ltp']:.2f} ({curr_pnl:+.1f}%) | Room to 0.8T1: {dist_to_t1_80:.1f}%")

print(f" ... and {len(data['active_valid']) - 15} more active setups.")
