# Oracle Cloud Deployment — Price Action Strategy System

This directory contains deployment, synchronization, and systemd management tools for the Price Action Trading System running on **Oracle Cloud Infrastructure (OCI)** Always-Free VMs.

---

## 🖥️ Production Cloud Environments

The Price Action Trading system is deployed across two dedicated Oracle Cloud VMs:

### 1. Bhavni Production VM
- **SSH Command**: `ssh -i "G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key" opc@129.225.69.131`
- **Host**: `129.225.69.131`
- **User**: `opc`
- **Remote Directory**: `/home/trade/Trade_Kite/Price_Action_Strategy`
- **Dashboards**:
  - Options Dashboard (Port 5050): `http://129.225.69.131:5050`
  - Stock Dashboard (Port 5051): `http://129.225.69.131:5051`

### 2. Poovendan Production VM
- **SSH Command**: `ssh -i "G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key" opc@140.245.197.71`
- **Host**: `140.245.197.71`
- **User**: `opc`
- **Remote Directory**: `/home/opc/Price_Action_Strategy`
- **Dashboards**:
  - Options Dashboard (Port 5050): `http://140.245.197.71:5050`
  - Stock Dashboard (Port 5051): `http://140.245.197.71:5051`

---

## 🚀 One-Click Code Synchronization & Deployment

To sync local code updates to Oracle Cloud VMs without overwriting remote account tokens:

```bash
# Check status of both VMs
python oracle/sync_to_oracle_cloud.py --status

# Sync and restart services on Bhavni VM only
python oracle/sync_to_oracle_cloud.py --target bhavni

# Sync and restart services on Poovendan VM only
python oracle/sync_to_oracle_cloud.py --target poovendan

# Sync and restart services on Both VMs
python oracle/sync_to_oracle_cloud.py --target all
```

Or double-click `oracle/SYNC_AND_START_ORACLE_CLOUD.bat` on Windows.

---

## ⚙️ Systemd Service Management

Each VM manages three background systemd services configured via `setup_systemd_vm.sh`:

1. **`trading-options.service`** — Price Action Options Dashboard & Trade Engines (Port 5050)
2. **`trading-stock.service`** — Price Action Stock Dashboard & Scanners (Port 5051)
3. **`trading-export.service`** — Daily Strategy Export Scheduler Daemon

### Common Systemd Commands:
```bash
# Check status
sudo systemctl status trading-options trading-stock trading-export

# Restart services
sudo systemctl restart trading-options trading-stock trading-export

# Stop services
sudo systemctl stop trading-options trading-stock trading-export

# View live service logs
journalctl -u trading-options -f
journalctl -u trading-stock -f
journalctl -u trading-export -f
```

---

## 🔑 Daily Zerodha Kite Token Refresh

Each morning before market open (09:00 AM IST):
1. SSH into the respective VM.
2. Run token generator:
   ```bash
   source venv/bin/activate
   python Kite_Access_Token_gen.py
   ```
3. Follow browser login and paste the redirect URL.
4. Restart services:
   ```bash
   sudo systemctl restart trading-options trading-stock
   ```
