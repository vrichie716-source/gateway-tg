# Hosting the bot for free (Google Cloud, no Oracle/Railway)

Use **Google Cloud Always Free** with an `e2-micro` VM (eligible regions) and Docker.

> Note: no free platform can guarantee exact 99% uptime forever, but this is one of the strongest non-Oracle free options for 24/7 bots.

## 1) Create VM (Always Free eligible)

- Provider: Google Cloud
- Machine: `e2-micro`
- OS: Ubuntu 22.04 LTS
- Region: pick an Always Free eligible US region
- Disk: standard persistent disk (small)
- Firewall: allow SSH (`tcp:22`)

## 2) SSH and bootstrap

Run on the VM:

```bash
sudo apt update -y && sudo apt install -y git
git clone https://github.com/vrichie716-source/gateway-tg.git
cd gateway-tg
bash scripts/bootstrap_gcp.sh
```

If `.env` did not exist, script stops so you can edit it first.

## 3) Configure `.env`

```dotenv
BOT_TOKEN=YOUR_BOT_TOKEN
GROUP_IDS=-1003808734183,-1003857658928
GROUP_NAMES=Chat,Main
```

## 4) Start and verify

```bash
cd ~/gateway-tg
docker compose up -d --build
docker compose ps
docker compose logs -f
```

## 5) Keep it stable

- VM restart policy is handled by Docker (`restart: unless-stopped`).
- Avoid stopping/deleting VM instance.
- Keep enough free-tier quota (single e2-micro, small disk).

## 6) Update after code changes

```bash
cd ~/gateway-tg
git pull
docker compose up -d --build
```
