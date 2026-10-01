import os
import glob

def check_paths():
    print("=== CHECKING CANONICAL ROOT AND OTHER DRIVES ===")
    roots = [
        r"G:\Poovendan\AI\Trading\Share\ReadyToDeploy\Prod_code_01\Price_Action_Strategy",
        r"G:\Poovendan\AI\Trading",
        r"C:\Users\poovendan\Desktop\personal\AI\Trade",
        r"C:\Trading",
        r"D:\Trading"
    ]
    for r in roots:
        exists = os.path.exists(r)
        print(f"Path: {r} -> Exists: {exists}")
        if exists:
            # Look for trade dbs, json, csv
            for root, dirs, files in os.walk(r):
                for f in files:
                    if any(x in f.lower() for x in ['trade', 'journal', 'order', 'position', 'pnl', 'loss', 'db', 'sqlite']):
                        full = os.path.join(root, f)
                        try:
                            sz = os.path.getsize(full)
                            if sz > 0:
                                print(f"  {full} ({sz} bytes)")
                        except Exception:
                            pass

if __name__ == '__main__':
    check_paths()
