import json

def run():
    with open('scratch/ultracemco_opt_candles.json') as f:
        ultra_opt = json.load(f)
    with open('scratch/lici_opt_candles.json') as f:
        lici_opt = json.load(f)

    print("=== ULTRACEMCO 10900 PE TIMELINE (Today) ===")
    for c in ultra_opt[-15:]:
        print(f"{c[0][11:16]} | Opt Open: {c[1]:<7.2f} High: {c[2]:<7.2f} Low: {c[3]:<7.2f} Close: {c[4]:<7.2f} Vol: {c[5]}")

    print("\n=== LICI 395 CE TIMELINE (Today) ===")
    for c in lici_opt[-15:]:
        print(f"{c[0][11:16]} | Opt Open: {c[1]:<7.2f} High: {c[2]:<7.2f} Low: {c[3]:<7.2f} Close: {c[4]:<7.2f} Vol: {c[5]}")

if __name__ == '__main__':
    run()
