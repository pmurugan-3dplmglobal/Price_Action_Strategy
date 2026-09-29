import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

def check(name, user, ip):
    print(f"=== {name} ({ip}) ===")
    cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"{user}@{ip}", "ps aux | grep -E 'python.*(engine|Trade|scanner)' | grep -v grep"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    print(res.stdout.strip() or "NO MATCHING PROCESSES")

if __name__ == "__main__":
    check("Poovendan VM1", "opc", "140.245.197.71")
    check("Bhavani VM2", "trade", "129.225.69.131")
