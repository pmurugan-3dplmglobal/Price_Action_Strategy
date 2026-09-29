import json, glob, os

files = glob.glob('/home/opc/Price_Action_Strategy/output/monitor/*.json')
for f in files:
    try:
        with open(f, 'r') as fp:
            d = json.load(fp)
        content_str = json.dumps(d)
        if 'COLPAL' in content_str or 'SBILIFE' in content_str or 'MOTHERSON' in content_str:
            print('Found in', os.path.basename(f))
            if isinstance(d, dict):
                for k, v in d.items():
                    if isinstance(v, list):
                        for item in v:
                            if isinstance(item, dict) and any(s in str(item) for s in ['COLPAL', 'SBILIFE', 'MOTHERSON']):
                                print("  [" + str(k) + "] sym=" + str(item.get('symbol')) + " cnt=" + str(item.get('contract')) + " pat=" + str(item.get('pattern')) + " tf=" + str(item.get('timeframe')) + " stage=" + str(item.get('stage')) + " tier=" + str(item.get('tier_badge') or item.get('tier_label')) + " bm=" + str(item.get('benchmark')) + " sl=" + str(item.get('current_sl') or item.get('sl')) + " t1=" + str(item.get('t1')))
    except Exception as e:
        pass
