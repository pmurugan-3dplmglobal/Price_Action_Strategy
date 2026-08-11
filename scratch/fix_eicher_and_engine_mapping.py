import sys, os, json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common")))
import paths

def fix_db():
    act_file = paths.ACTIVE_POSITIONS_DB
    trades_file = paths.TRADES_DB

    # 1. Clean active_positions_db.json
    if os.path.exists(act_file):
        with open(act_file, "r", encoding="utf-8") as f:
            act_data = json.load(f)
        pos_list = act_data.get("positions", [])
        new_pos = []
        for p in pos_list:
            c = str(p.get("contract") or p.get("symbol") or "").replace(" ", "").upper()
            pid = p.get("id")
            # Remove ghost EICHERMOT26AUG8000PE (id 20) and duplicate TMPV (id 6)
            if pid == 20 or (pid == 6 and c == "TMPV26AUG350PE"):
                print(f"Removing orphan/duplicate active position id {pid}: {c}")
                continue
            new_pos.append(p)
        act_data["positions"] = new_pos
        with open(act_file, "w", encoding="utf-8") as f:
            json.dump(act_data, f, indent=2)

    # 2. Clean trades_db.json
    if os.path.exists(trades_file):
        with open(trades_file, "r", encoding="utf-8") as f:
            tr_data = json.load(f)
        trades = tr_data.get("trades", [])
        for t in trades:
            if t.get("id") == 20:
                print("Updating trade id 20 to SL_HIT to match EICHERMOT execution...")
                t["status"] = "SL_HIT"
                t["engine"] = "nifty50"
                t["symbol"] = "EICHERMOT"
                t["entry_spot"] = 140.0
                t["exit_time"] = "2026-08-10 13:28:32"
                t["pnl_percent"] = -10.71
                t["details"] = "SL hit [CANDLE_CLOSE_SL (75min Bar @ 2026-08-10 13:00:00+05:30)] | TF: 75min"
            elif t.get("id") == 6:
                print("Updating duplicate trade id 6 to engine nifty50...")
                t["engine"] = "nifty50"
                t["symbol"] = "TMPV"
        tr_data["trades"] = trades
        with open(trades_file, "w", encoding="utf-8") as f:
            json.dump(tr_data, f, indent=2)

    print("Cleanup complete.")

if __name__ == "__main__":
    fix_db()
