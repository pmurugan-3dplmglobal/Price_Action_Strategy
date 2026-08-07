import json
import os

print("=== ACTIVE POSITIONS DB ===")
p_act = 'Trade_Option/output/monitor/active_positions_db.json'
if os.path.exists(p_act):
    data = json.load(open(p_act))
    for p in data.get('positions', []):
        if 'WIPRO' in str(p):
            print(json.dumps(p, indent=2))

print("\n=== TRADES DB ===")
p_tr = 'Trade_Option/output/monitor/trades_db.json'
if os.path.exists(p_tr):
    data = json.load(open(p_tr))
    for p in data.get('trades', []):
        if 'WIPRO' in str(p):
            print(json.dumps(p, indent=2))

print("\n=== OVERRIDES DB ===")
p_ov = 'Trade_Option/output/monitor/sl_target_overrides.json'
if os.path.exists(p_ov):
    data = json.load(open(p_ov))
    for sec in data:
        for k in data[sec]:
            if 'WIPRO' in k:
                print(sec, k, data[sec][k])
