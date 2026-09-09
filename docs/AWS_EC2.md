# AWS EC2 Ubuntu deployment

For unattended live-market **paper** operation, a small Ubuntu EC2 instance is a better fit than a laptop WSL host because it can remain online independently of a desktop session. WSL is still recommended for local development and replay.

## Free-tier caveat

AWS Free Tier eligibility depends on when the AWS account was created and the current Free Tier plan. As of 2026, AWS documents different eligible instance families for older versus newer accounts, and newer accounts use credits/free-plan limits rather than an unconditional forever-free server. Check the current AWS Free Tier page before launching and set billing/usage alerts. Do not assume an instance is free indefinitely.

## Recommended host

Use **Ubuntu Server LTS** on a free-tier-eligible EC2 instance available to your account. A small burstable instance such as `t3.micro` or `t4g.micro` can be adequate for this paper workload if it is eligible for your account and the data adapter does not require more CPU or memory. Choose the architecture that matches your Python/data-provider dependencies.

Suggested starting layout:

- 1 EC2 instance
- Ubuntu Server LTS
- 8–16 GB gp3 EBS is generally enough for the application and SQLite history; expand only when needed
- one security group
- SSH inbound only from your own IP
- no public HTTP/HTTPS ports
- SQLite/WAL and logs on the Linux filesystem
- systemd for the agent and daily maintenance

## Launch checklist

1. Open EC2 in the AWS console and choose **Launch instance**.
2. Select an Ubuntu Server LTS AMI.
3. Select a Free-Tier-eligible instance type shown for your account.
4. Create/select an SSH key pair and store the private key securely outside the repository.
5. Configure a security group with SSH (`22`) restricted to **your current public IP**, not `0.0.0.0/0`.
6. Do not open web ports because the agent does not expose a web server.
7. Keep the instance in the region with the lowest operational latency that makes sense for your data-provider endpoint; the exchange itself remains NSE/India.
8. Enable AWS billing/free-tier usage alerts.

## Connect

From your local machine:

```bash
ssh -i /path/to/key.pem ubuntu@YOUR_EC2_PUBLIC_IP
```

## Install the agent

```bash
sudo apt-get update
sudo apt-get install -y git python3.11 python3.11-venv sqlite3
sudo useradd --system --home /opt/nse-paper-agent --shell /usr/sbin/nologin nse-paper
sudo mkdir -p /opt/nse-paper-agent /etc/nse-paper-agent /var/lib/nse-paper-agent /var/log/nse-paper-agent /var/backups/nse-paper-agent /run/nse-paper-agent
sudo chown -R nse-paper:nse-paper /opt/nse-paper-agent /var/lib/nse-paper-agent /var/log/nse-paper-agent /var/backups/nse-paper-agent /run/nse-paper-agent
sudo -u nse-paper git clone https://github.com/himansh241291/DoorDieAgent.git /opt/nse-paper-agent
sudo -u nse-paper python3.11 -m venv /opt/nse-paper-agent/.venv
sudo -u nse-paper /opt/nse-paper-agent/.venv/bin/pip install --upgrade pip
sudo -u nse-paper /opt/nse-paper-agent/.venv/bin/pip install -r /opt/nse-paper-agent/requirements.txt
sudo -u nse-paper /opt/nse-paper-agent/.venv/bin/pip install -e /opt/nse-paper-agent
```

Copy `config/production.paper.yaml`, strategy files, and the maintained NSE holiday calendar into `/etc/nse-paper-agent/`. Create a protected EnvironmentFile at `/etc/nse-paper-agent/nse-paper-agent.env` if notifications are enabled. Never put broker credentials in it; this deployment has no broker execution.

## Acceptance gate

Run all tests before attaching a live market-data adapter:

```bash
cd /opt/nse-paper-agent
sudo -u nse-paper /opt/nse-paper-agent/.venv/bin/pytest
sudo -u nse-paper /opt/nse-paper-agent/.venv/bin/python scripts/initialize_db.py --config /etc/nse-paper-agent/production.paper.yaml
sudo -u nse-paper /opt/nse-paper-agent/.venv/bin/python scripts/run_replay.py --bars /opt/nse-paper-agent/tests/fixtures/sample_bars.csv --db /tmp/nse-paper-replay.sqlite3
```

## systemd

```bash
sudo cp /opt/nse-paper-agent/systemd/*.service /etc/systemd/system/
sudo cp /opt/nse-paper-agent/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nse-paper-agent.service
sudo systemctl enable --now nse-paper-maintenance.timer
sudo systemctl status nse-paper-agent.service
```

## Operations

```bash
sudo journalctl -u nse-paper-agent -f
sudo systemctl restart nse-paper-agent
sudo systemctl stop nse-paper-agent
sudo systemctl status nse-paper-maintenance.timer
```

Emergency entry halt:

```bash
sudo touch /etc/nse-paper-agent/KILL_SWITCH
```

The kill switch blocks new simulated entries but leaves existing simulated exits active.

## AWS cost and security hygiene

- Monitor Free Tier usage and account credits; do not treat the server as guaranteed free forever.
- Keep SSH restricted to your IP and rotate/revoke keys if exposed.
- Do not expose a public monitoring endpoint unless one is explicitly designed and security-reviewed.
- Store no broker credentials on this host because the current project is paper-only.
- Back up the SQLite database to a protected location and test restore procedures.
- Stop/terminate the instance when you no longer need it if you are outside the applicable free allowance.
