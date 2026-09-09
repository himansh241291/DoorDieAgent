# Running the NSE Paper Agent under WSL2

WSL2 is supported for continuous paper trading. The agent remains paper-only: a future live market-data adapter can feed prices, but every order is simulated by `PaperBroker`.

## Enable systemd

Inside WSL:

```bash
sudo tee /etc/wsl.conf >/dev/null <<'CONF'
[boot]
systemd=true
CONF
```

From Windows PowerShell:

```powershell
wsl --shutdown
```

Then verify `systemctl is-system-running`.

## Clone and install

```bash
git clone https://github.com/himansh241291/DoorDieAgent.git
cd DoorDieAgent
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv sqlite3 git
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
pytest
```

Keep the database and logs on the Linux filesystem rather than `/mnt/c` when possible.

## Offline acceptance gate

```bash
python scripts/initialize_db.py --config config/production.paper.yaml
python scripts/run_replay.py --bars tests/fixtures/sample_bars.csv --db /tmp/nse-paper-replay.sqlite3
pytest
```

Only after the offline gate passes should a deployment-specific live market-data ingestion adapter be introduced.

## systemd

For a dedicated WSL installation, use the supplied unit files and the paths in the main README. Keep an unprivileged `nse-paper` user and the service paper-only.

```bash
sudo cp systemd/*.service systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nse-paper-agent.service
sudo systemctl enable --now nse-paper-maintenance.timer
```

WSL must remain running during NSE market hours. Sleep, shutdown, WSL termination, network changes, or laptop resource pressure can interrupt connectivity; the agent must fail closed on stale or unhealthy data.

## Emergency entry halt

```bash
sudo touch /etc/nse-paper-agent/KILL_SWITCH
```

This blocks future paper entries while leaving existing simulated exits active.

For unattended production-like operation, an always-on AWS Ubuntu EC2 host is preferable to a laptop WSL environment. WSL remains useful for development, replay, and testing.
