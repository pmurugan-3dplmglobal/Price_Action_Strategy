import json
import os
import sys

p_act = 'Trade_Option/output/monitor/active_positions_db.json'
if os.path.exists(p_act):
    data = json.load(open(p_act))
    for p in data.get('positions', []):
        sym = str(p.get('contract') or p.get('symbol')).upper()
        if any(k in sym for k in ['MARUTI', 'INDIGO', 'JIOFIN']):
            print("=== POSITION ===")
            print(json.dumps(p, indent=2))
