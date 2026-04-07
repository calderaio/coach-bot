# Coach Bot — Setup Guide

## What this does
A lightweight server that watches your #coach Slack channel and responds automatically via Claude whenever you post a message. Fully automatic — no manual triggers.

---

## Step 1 — Create a Slack App

1. Go to https://api.slack.com/apps → **Create New App** → **From scratch**
2. Name it `Coach`, select your workspace (`calderaio`)
3. Go to **OAuth & Permissions** → add these Bot Token Scopes:
   - `chat:write`
   - `channels:history`
   - `channels:read`
4. Click **Install to Workspace** → copy the **Bot OAuth Token** (starts with `xoxb-`)
5. Go to **Basic Information** → copy the **Signing Secret**
6. Go to **App Home** → enable **Messages Tab**
7. Invite the bot to #coach: in Slack type `/invite @Coach`

---

## Step 2 — Deploy to Railway

1. Go to https://railway.app → New Project → **Deploy from GitHub repo**
   (push coach_bot.py and requirements.txt to a new GitHub repo first)
2. Set these environment variables in Railway:
   ```
   ANTHROPIC_API_KEY=your_anthropic_key
   SLACK_BOT_TOKEN=xoxb-your-bot-token
   SLACK_SIGNING_SECRET=your-signing-secret
   ```
3. Railway will give you a public URL like `https://coach-bot.up.railway.app`

---

## Step 3 — Connect Slack Events

1. Back in your Slack app → **Event Subscriptions** → Enable Events
2. Set Request URL to: `https://your-railway-url/slack/events`
   (Slack will verify it — the bot handles this automatically)
3. Subscribe to bot events: add `message.channels`
4. Save changes → reinstall the app if prompted

---

## Step 4 — Test it

Post anything in #coach. The bot should respond within a few seconds.

---

## Procfile (for Railway)
```
web: gunicorn coach_bot:app
```
Create this file in the same repo.
