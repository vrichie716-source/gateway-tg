# GitHub Actions fallback hosting (no cloud billing)

This runs the bot on GitHub Actions in rolling jobs so your PC does not need to stay on.

## What it uses

- Workflow: [.github/workflows/bot_runner.yml](.github/workflows/bot_runner.yml)
- Secrets required in your GitHub repo:
  - `BOT_TOKEN`
  - `GROUP_IDS` (example: `-1003808734183,-1003857658928`)
  - `GROUP_NAMES` (example: `Chat,Main`)

## Behavior

- Scheduled every 30 minutes as backup trigger.
- Each run keeps the bot process alive for ~5h45m with auto-restart loop if it crashes.
- At the end of each run, the workflow dispatches the next run automatically (chained runs).
- Concurrency is single-instance (`gateway-tg-bot-runner`) to avoid overlap from this workflow.
- Also supports manual start via `workflow_dispatch`.

## Required workflow permissions

- `actions: write` (needed for self-dispatch chaining)
- `contents: read`

These are already configured in `.github/workflows/bot_runner.yml`.

## Important limits

- This is the best possible no-billing fallback, but still not a strict SLA host.
- Runtime depends on GitHub Actions minutes/quota and GitHub availability.
- If any other host (Railway/GCP/Oracle/local PC) runs the same token simultaneously, Telegram returns 409 Conflict and one instance will stop.
- For stronger uptime, move to a paid VPS later.
