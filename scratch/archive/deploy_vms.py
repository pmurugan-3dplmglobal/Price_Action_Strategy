#!/usr/bin/env python3
"""
scratch/deploy_vms.py
Convenience wrapper to deploy the codebase to Bhavni and Poovendan Oracle Cloud VMs.
"""
import sys
import os
import subprocess

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SYNC_SCRIPT = os.path.join(PROJECT_ROOT, "oracle", "sync_to_oracle_cloud.py")

def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    cmd = [sys.executable, SYNC_SCRIPT, "--target", target]
    print(f"Executing: {' '.join(cmd)}")
    ret = subprocess.run(cmd)
    sys.exit(ret.returncode)

if __name__ == "__main__":
    main()
