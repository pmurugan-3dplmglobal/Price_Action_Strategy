import json

with open('input/watchlist.json') as f:
    wl = json.load(f)

print(f"Total entries in watchlist.json: {len(wl)}")
tags = {}
for item in wl:
    t = item.get('tag', 'NONE')
    tags[t] = tags.get(t, 0) + 1

print("Tags distribution:", tags)
print("\nFirst 15 items in watchlist.json:")
for item in wl[:15]:
    sym = item.get('base_symbol')
    cnt = item.get('contract')
    entry = item.get('entry_price')
    exit_p = item.get('exit_price')
    tag = item.get('tag')
    note = item.get('note')
    lot = item.get('lot_size')
    pnl = (exit_p - entry) * lot if (entry and exit_p and lot) else 0
    pnl_pct = (exit_p - entry) / entry * 100 if (entry and exit_p) else 0
    print(f"{sym:<12} | {cnt:<24} | Entry: {entry:<6} | Exit: {exit_p:<6} | PnL%: {pnl_pct:>+6.1f}% | PnL: Rs {pnl:>+9.2f} | Tag: {tag:<18} | {note}")
