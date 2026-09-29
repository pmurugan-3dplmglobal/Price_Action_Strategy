import subprocess

SSH_KEY = r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key'
VMS = [
    ('VM1 (Poovendan)', '140.245.197.71', 'opc', '/home/opc/Price_Action_Strategy', '/home/opc/Price_Action_Strategy/venv/bin/python'),
    ('VM2 (Bhavani)', '129.225.69.131', 'opc', '/home/trade/Trade_Kite/Price_Action_Strategy', '/home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python')
]

REMOTE_SCRIPT = """
import sys, os, json, sqlite3
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), 'common'))

try:
    from kiteconnect import KiteConnect
    from session import load_kite_session
    ak, at = load_kite_session()
    kite = KiteConnect(api_key=ak)
    kite.set_access_token(at)
    
    prof = kite.profile()
    print(f"USER: {prof.get('user_id')} - {prof.get('user_name')}")
    
    pos = kite.positions()
    net = pos.get('net', [])
    print(f"Total Net Positions: {len(net)}")
    tot_pnl = 0.0
    for p in net:
        ts = p.get('tradingsymbol')
        qty = p.get('quantity')
        buy_p = p.get('average_price')
        sell_p = p.get('sell_price')
        ltp = p.get('last_price')
        pnl = p.get('pnl')
        tot_pnl += pnl
        status = 'OPEN' if qty != 0 else 'CLOSED'
        if qty != 0 or pnl != 0:
            print(f"  [{status}] {ts:<25} Qty: {qty:<6} Buy: {buy_p:<8.2f} Sell: {sell_p:<8.2f} LTP: {ltp:<8.2f} PnL: {pnl:<10.2f}")
    print(f"TOTAL PNL: Rs {tot_pnl:,.2f}")
    
    ords = kite.orders()
    print(f"\\nTotal Orders Today: {len(ords)}")
    for o in ords:
        ts = str(o.get('order_timestamp'))
        print(f"  ORD: {ts:<20} {o.get('tradingsymbol'):<25} {o.get('transaction_type'):<5} Qty: {o.get('quantity'):<6} Avg: {o.get('average_price', 0):<8.2f} Stat: {o.get('status'):<10} Tag: {o.get('tag')} GUID: {o.get('guid')}")
except Exception as e:
    import traceback
    traceback.print_exc()
"""

for name, ip, user, dir_, py in VMS:
    print(f"\n{'='*70}\n{name} ({ip})\n{'='*70}")
    ssh_cmd = [
        'ssh', '-i', SSH_KEY,
        '-o', 'StrictHostKeyChecking=no',
        f"{user}@{ip}",
        f"cd {dir_} && {py} -"
    ]
    res = subprocess.run(ssh_cmd, input=REMOTE_SCRIPT, capture_output=True, text=True)
    print(res.stdout)
    if res.stderr and 'Permanently added' not in res.stderr:
        print("STDERR:", res.stderr)
