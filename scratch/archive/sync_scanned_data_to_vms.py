import subprocess
import os
import sys

SSH_KEY = r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key'

VMS = [
    {
        'name': 'VM1 (Poovendan)',
        'ip': '140.245.197.71',
        'user': 'opc',
        'remote_dir': '/home/opc/Price_Action_Strategy'
    },
    {
        'name': 'VM2 (Bhavani)',
        'ip': '129.225.69.131',
        'user': 'opc',
        'remote_dir': '/home/trade/Trade_Kite/Price_Action_Strategy'
    }
]

FILES_TO_SYNC = [
    ('output/monitor/scan_display.json', 'output/monitor/scan_display.json'),
    ('output/monitor/scan_display_index.json', 'output/monitor/scan_display_index.json'),
    ('output/monitor/pattern_funnel.json', 'output/monitor/pattern_funnel.json'),
    ('output/monitor/cycle_trades.json', 'output/monitor/cycle_trades.json'),
    ('input/watchlist.json', 'input/watchlist.json'),
]

def main():
    print("=" * 70)
    print("SYNCING SCANNED DATA FILES FROM LOCAL TO CLOUD VMS")
    print("=" * 70)

    # Verify local files exist
    for local_rel, _ in FILES_TO_SYNC:
        if not os.path.exists(local_rel):
            print(f"[ERROR] Local file not found: {local_rel}")
            sys.exit(1)
        sz = os.path.getsize(local_rel)
        print(f"  -> Local ready: {local_rel} ({sz:,} bytes)")

    all_ok = True
    for vm in VMS:
        print(f"\n{'-'*70}")
        print(f"Syncing to {vm['name']} ({vm['ip']})...")
        print(f"Remote base directory: {vm['remote_dir']}")
        print(f"{'-'*70}")

        # Ensure remote directories exist
        ensure_dirs_cmd = [
            'ssh', '-i', SSH_KEY,
            '-o', 'StrictHostKeyChecking=no',
            f"{vm['user']}@{vm['ip']}",
            f"mkdir -p {vm['remote_dir']}/output/monitor {vm['remote_dir']}/input"
        ]
        res_dir = subprocess.run(ensure_dirs_cmd, capture_output=True, text=True)
        if res_dir.returncode != 0:
            print(f"  [ERROR] Failed to ensure remote directories: {res_dir.stderr}")
            all_ok = False
            continue

        for local_rel, remote_rel in FILES_TO_SYNC:
            remote_full = f"{vm['remote_dir']}/{remote_rel}"
            scp_cmd = [
                'scp', '-i', SSH_KEY,
                '-o', 'StrictHostKeyChecking=no',
                local_rel,
                f"{vm['user']}@{vm['ip']}:{remote_full}"
            ]
            res_scp = subprocess.run(scp_cmd, capture_output=True, text=True)
            if res_scp.returncode == 0:
                print(f"  [OK] Uploaded {local_rel} -> {remote_full}")
            else:
                print(f"  [ERROR] Upload failed for {local_rel}:\n{res_scp.stderr}")
                all_ok = False

        # Verify on remote VM
        py_check = (
            "import json, os\n"
            f"base = '{vm['remote_dir']}'\n"
            "for p in [f'{base}/output/monitor/scan_display.json', f'{base}/output/monitor/scan_display_index.json', f'{base}/output/monitor/pattern_funnel.json']:\n"
            "    if os.path.exists(p):\n"
            "        with open(p, 'r') as f:\n"
            "            d = json.load(f)\n"
            "        items = d.get('all_staged_today', []) or d.get('staged_trades', []) or d.get('candidates', []) or []\n"
            "        print('Verified ' + os.path.basename(p) + ': valid JSON, size=' + str(os.path.getsize(p)) + ' bytes, items=' + str(len(items)))\n"
            "    else:\n"
            "        print('Missing: ' + p)\n"
        )
        verify_cmd = [
            'ssh', '-i', SSH_KEY,
            '-o', 'StrictHostKeyChecking=no',
            f"{vm['user']}@{vm['ip']}",
            'python3 -c "' + py_check.replace('\n', '; ') + '"'
        ]
        res_ver = subprocess.run(verify_cmd, capture_output=True, text=True)
        print("Remote verification:")
        print(res_ver.stdout.strip())
        if res_ver.stderr:
            print("Remote stderr:", res_ver.stderr.strip())

    print("\n" + "=" * 70)
    if all_ok:
        print(">>> ALL SCANNED DATA FILES SUCCESSFULLY SYNCED TO BOTH VMS! <<<")
    else:
        print(">>> WARNING: Some files failed to sync. Check output above. <<<")
    print("=" * 70)

if __name__ == '__main__':
    main()
