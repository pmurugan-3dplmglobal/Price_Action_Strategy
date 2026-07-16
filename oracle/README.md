# Oracle Cloud Deployment — Trading Control Center

This folder contains scripts to run the trading bot on an **Oracle Cloud Free Tier** VM
(Always-Free, Ubuntu) on a market-hours schedule (9:00 AM – 3:30 PM IST, Mon–Fri).

## Files
- `start_bot.sh`   — Launches `app.py` (Flask dashboard on 0.0.0.0:5051) at market open.
- `stop_bot.sh`    — Gracefully stops engines + dashboard at market close.
- `check_token.sh` — Verifies the daily Kite token is fresh; prints ACTION REQUIRED if stale.

## One-time VM setup (SSH into the VM)
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-pip python3-venv git -y
sudo timedatectl set-timezone Asia/Kolkata

# Upload project (from your PC):
#   scp -i key.pem -r /path/to/Prod_code_02 ubuntu@<PUBLIC_IP>:~
cd ~/Prod_code_02
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Place your secrets (DO NOT commit):
#   input/program_config.json
#   input/kite_access_token.txt
```

## Open the dashboard port in OCI
In the OCI Console → VCN → Security Lists → add Ingress rule:
TCP, destination port **5051**, source **0.0.0.0/0**.

## Schedule — Option A: systemd (recommended, more robust)
Provides auto-restart on crash, proper logging, and clean process management.

```bash
chmod +x oracle/*.sh
sudo bash oracle/install_systemd.sh
```
This installs:
- `trading-dashboard.service` — runs `app.py`, restarts on failure, 8h safety cap
- `trading-start.timer`       — starts dashboard at 9:00 AM IST
- `trading-stop.timer`        — stops engines + dashboard at 3:30 PM IST
- `trading-stop.service`      — oneshot that runs `stop_bot.sh`

Manual control:
```bash
sudo systemctl start trading-dashboard.service
sudo systemctl stop  trading-dashboard.service
systemctl status trading-dashboard.service
systemctl list-timers | grep trading
```

## Schedule — Option B: cron (simpler fallback)
```bash
chmod +x oracle/*.sh
crontab -e
```
Add:
```cron
# Start at 9:00 AM IST, weekdays
0 9 * * 1-5 /home/ubuntu/Prod_code_02/oracle/start_bot.sh

# Stop at 3:30 PM IST, weekdays
30 15 * * 1-5 /home/ubuntu/Prod_code_02/oracle/stop_bot.sh
```

## Daily Kite token (manual — Zerodha needs 2FA)
Tokens expire daily. Each morning before 9 AM:
```bash
ssh ubuntu@<PUBLIC_IP>
cd ~/Prod_code_02 && source venv/bin/activate
python Kite_Access_Token_gen.py   # paste redirect URL from browser login
```
`start_bot.sh` warns in `output/bot_start.log` if the token is stale.

## Logs
- `output/bot_start.log`   — launch + token status
- `output/bot_stop.log`    — shutdown
- `output/dashboard.log`   — Flask app output
- `output/token_check.log` — token freshness checks
