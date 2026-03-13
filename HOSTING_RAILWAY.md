# Hosting on Railway.com

Railway deploys from your GitHub repo and runs the bot via `Dockerfile`.

## 1) Connect GitHub repo

- Go to [railway.com](https://railway.com) → **New Project** → **Deploy from GitHub repo**
- Select `vrichie716-source/gateway-tg`
- Railway auto-detects the `Dockerfile` and builds from it

## 2) Set environment variables

Go to your service → **Variables** tab and add:

```dotenv
BOT_TOKEN=YOUR_BOT_TOKEN
GROUP_IDS=-1003808734183,-1003857658928
GROUP_NAMES=Chat,Main
TELEGRAM_API_ID=YOUR_API_ID
TELEGRAM_API_HASH=YOUR_API_HASH
```

## 3) Deployment mode

The bot runs in **polling mode** by default (no public domain needed).

If you want webhook mode instead, assign a public domain under **Settings → Networking → Generate Domain**. The bot will detect `RAILWAY_PUBLIC_DOMAIN` and switch to webhook mode automatically.

## 4) Verify

- Check **Deployments** tab — status should be green
- Send `/start` to the bot on Telegram

## 5) Update after code changes

Push to `main` on GitHub — Railway auto-redeploys.
