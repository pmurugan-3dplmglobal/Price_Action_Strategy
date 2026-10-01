import os
import glob
import sqlite3
import json

def check_local():
    print("=== SEARCHING LOCAL DATABASES & LOGS ===")
    files = glob.glob('**/*.sqlite', recursive=True) + glob.glob('**/*.db', recursive=True)
    for db in files:
        if "venv" in db or ".git" in db:
            continue
        print(f"\nDB: {db}")
        try:
            conn = sqlite3.connect(db)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cur.fetchall()
            for t in tables:
                tname = t[0]
                cur.execute(f"SELECT count(*) FROM {tname}")
                cnt = cur.fetchone()[0]
                print(f"  Table {tname}: {cnt} rows")
                if cnt > 0:
                    cur.execute(f"SELECT * FROM {tname} ORDER BY rowid DESC LIMIT 5")
                    rows = cur.fetchall()
                    col_names = [d[0] for d in cur.description]
                    print(f"    Columns: {col_names}")
                    for r in rows:
                        print(f"    {r}")
            conn.close()
        except Exception as e:
            print(f"  Error reading {db}: {e}")

    print("\n=== SEARCHING LOGS & OUTPUT FILES FOR TRADES ===")
    for pattern in ['Trade_Option/output/*.json', 'output/*.json', 'Trade_Option/logs/*.log', 'logs/*.log']:
        for f in glob.glob(pattern):
            sz = os.path.getsize(f)
            print(f"File: {f} ({sz} bytes)")

if __name__ == '__main__':
    check_local()
