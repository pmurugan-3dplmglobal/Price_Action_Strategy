import json

def inspect():
    with open('scratch/archive/today_forensic_results.json') as f:
        forensic = json.load(f)
    print("=== TRADES IN today_forensic_results.json ===")
    for item in forensic:
        print(f"Symbol: {item.get('symbol')} | Contract: {item.get('contract')} | Status: {item.get('status')} | Entry: {item.get('entry_p')} @ {item.get('entry_t')} | Exit: {item.get('exit_p')} @ {item.get('exit_t')} | PnL: {((item.get('exit_p') or item.get('entry_p')) - item.get('entry_p')) * item.get('lot', 0):.2f}")

    with open('scratch/archive/today_vm1_trades_db.json') as f:
        vm1 = json.load(f)
    print("\n=== TRADES IN today_vm1_trades_db.json ===")
    for item in vm1:
        data = json.loads(item.get('data_json', '{}'))
        print(f"ID: {item.get('id')} | Symbol: {item.get('symbol')} | Contract: {item.get('contract')} | Status: {item.get('status')} | Entry: {data.get('entry_price')} @ {data.get('entry_time')} | Exit: {data.get('exit_price')} @ {data.get('exit_time')} | PnL%: {data.get('pnl_percent')} | Details: {data.get('details')}")

    with open('scratch/archive/comparative_study_winners_vs_losers.json') as f:
        comp = json.load(f)
    print("\n=== TRADES IN comparative_study_winners_vs_losers.json ===")
    for item in comp:
        print(f"Group: {item.get('group')} | Symbol: {item.get('symbol')} | Contract: {item.get('contract')} | Pattern: {item.get('pattern')} | Benchmark: {item.get('benchmark')} | SL: {item.get('sl')} | Gain High%: {item.get('gain_high'):.2f}% | Current Gain%: {item.get('curr_gain'):.2f}%")

if __name__ == '__main__':
    inspect()
