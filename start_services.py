import subprocess
import sys
import os
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008

print("=" * 65)
print("     PRICE ACTION STRATEGY — STARTING LOCAL SERVICES")
print("=" * 65)

print("\n[1/2] Launching Options Dashboard on Port 5050...")
p1 = subprocess.Popen(
    [sys.executable, os.path.join(ROOT, "Trade_Option", "app_option_Trade.py")],
    cwd=ROOT,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    stdin=subprocess.DEVNULL,
    creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW
)
print(f"  -> Options Dashboard PID: {p1.pid}")

print("\n[2/2] Launching Stock Dashboard on Port 5051...")
p2 = subprocess.Popen(
    [sys.executable, os.path.join(ROOT, "Trade_Stock", "app_Stock_Trade.py")],
    cwd=ROOT,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    stdin=subprocess.DEVNULL,
    creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW
)
print(f"  -> Stock Dashboard PID: {p2.pid}")

time.sleep(3)

print("\n" + "=" * 65)
print("                    HEALTH CHECK & STATUS")
print("=" * 65)

# Test endpoints
try:
    r1 = urllib.request.urlopen("http://127.0.0.1:5050/")
    print(f" [OK] Options Dashboard running on http://localhost:5050 (HTTP {r1.status})")
except Exception as e:
    print(f" [WAIT] Options Dashboard starting: {e}")

try:
    r2 = urllib.request.urlopen("http://127.0.0.1:5051/")
    print(f" [OK] Stock Dashboard running on   http://localhost:5051 (HTTP {r2.status})")
except Exception as e:
    print(f" [WAIT] Stock Dashboard starting: {e}")

print("=" * 65)
