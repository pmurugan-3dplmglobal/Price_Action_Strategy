import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

data = json.load(open('scratch/post_entry_audit.json', encoding="utf-8"))

print("=" * 85)
print(f"1. 🎯 REACHED FULL T1 (POST-ENTRY): {len(data['post_t1'])} Setup(s)")
print("=" * 85)
for x in data['post_t1']:
    gain = ((x['post_high'] - x['entry']) / x['entry'] * 100) if x['entry'] else 0
    curr = ((x['ltp'] - x['entry']) / x['entry'] * 100) if x['entry'] else 0
    print(f"-> {x['symbol']} | Contract: {x['contract']} ({x['side']}) | Pattern: {x['pattern']}")
    print(f"   Entry Benchmark: {x['entry']:.2f} | SL: {x['sl']:.2f} | 0.8T1: {x['t1_80']:.2f} | Target 1: {x['t1']:.2f}")
    print(f"   Post-Entry High: {x['post_high']:.2f} (+{gain:.1f}%) | Post-Entry Low: {x['post_low']:.2f} | Current LTP: {x['ltp']:.2f} ({curr:+.1f}%)")
    print(f"   Entry Candle: {x.get('entry_time')}")

print("\n" + "=" * 85)
print(f"2. 🏃 REACHED 0.8T1 RUNAWAY (POST-ENTRY): {len(data['post_08_t1'])} Setup(s)")
print("=" * 85)
for x in data['post_08_t1']:
    gain = ((x['post_high'] - x['entry']) / x['entry'] * 100) if x['entry'] else 0
    curr = ((x['ltp'] - x['entry']) / x['entry'] * 100) if x['entry'] else 0
    print(f"-> {x['symbol']} | Contract: {x['contract']} ({x['side']}) | Pattern: {x['pattern']}")
    print(f"   Entry Benchmark: {x['entry']:.2f} | SL: {x['sl']:.2f} | 0.8T1: {x['t1_80']:.2f} | Target 1: {x['t1']:.2f}")
    print(f"   Post-Entry High: {x['post_high']:.2f} (+{gain:.1f}%) | Post-Entry Low: {x['post_low']:.2f} | Current LTP: {x['ltp']:.2f} ({curr:+.1f}%)")
    print(f"   Entry Candle: {x.get('entry_time')}")

print("\n" + "=" * 85)
print(f"3. 🛑 HIT SL (POST-ENTRY): {len(data['post_sl'])} Setup(s)")
print("=" * 85)
for x in data['post_sl']:
    curr = ((x['ltp'] - x['entry']) / x['entry'] * 100) if x['entry'] else 0
    drop = ((x['post_low'] - x['entry']) / x['entry'] * 100) if x['entry'] else 0
    print(f"-> {x['symbol']} | Contract: {x['contract']} ({x['side']}) | Pattern: {x['pattern']}")
    print(f"   Entry Benchmark: {x['entry']:.2f} | SL: {x['sl']:.2f} | Target 1: {x['t1']:.2f}")
    print(f"   Post-Entry Low: {x['post_low']:.2f} ({drop:.1f}%) | Current LTP: {x['ltp']:.2f} ({curr:+.1f}%)")
    print(f"   Entry Candle: {x.get('entry_time')}")

print("\n" + "=" * 85)
print(f"4. 🟢 TOP ACTIVE / IN-CORRIDOR SETUPS: Total {len(data['post_active'])} Setups")
print("=" * 85)
# Sort active by current gain
data['post_active'].sort(key=lambda x: ((x['ltp'] - x['entry']) / x['entry'] * 100) if x['entry'] else 0, reverse=True)
for x in data['post_active'][:10]:
    gain = ((x['ltp'] - x['entry']) / x['entry'] * 100) if x['entry'] else 0
    dist_80 = ((x['t1_80'] - x['ltp']) / x['entry'] * 100) if x['entry'] else 0
    print(f"-> {x['symbol']:12s} {x['contract']:22s} ({x['side']}) | Entry: {x['entry']:7.2f} | SL: {x['sl']:7.2f} | LTP: {x['ltp']:7.2f} ({gain:+6.1f}%) | Room to 0.8T1: {dist_80:5.1f}%")
