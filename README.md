# Coach Bot

A personal AI assistant running on Railway that handles three things:

- **Instant coaching** — responds to every message in the `#coach` Slack channel via Claude
- **Morning briefings** — daily DM with news across geopolitics, AI/tech, GIS, space, and Switzerland
- **Weekly review** — Sunday evening prompts in `#coach` to reflect on the week

---

## Architecture

```
cron-job.org ──POST──▶ Railway (Flask)
                            │
                            ├── /cron/morning-briefing
                            │       └── Serper (6 searches) → Claude → Slack DM
                            │
                            ├── /cron/weekly-review
                            │       └── Slack message → #coach
                            │
                            └── /slack/events
                                    └── Slack event → Claude → reply in #coach thread
```

**Services used:**
| Service | Purpose |
|---|---|
| [Railway](https://railway.app) | Hosts the Flask server |
| [Anthropic Claude](https://anthropic.com) | Powers coaching responses and briefing synthesis |
| [Serper](https://serper.dev) | Web search for morning briefings (2500 req/month free) |
| [Slack](https://api.slack.com) | Delivery channel for all output |
| [cron-job.org](https://cron-job.org) | Triggers the two cron endpoints |

---

## Files

```
coach_bot.py      — Flask app (all logic)
requirements.txt  — Python dependencies
Procfile          — Railway start command
```

---

## Environment Variables

Set these in Railway:

```
ANTHROPIC_API_KEY=
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=
SERPER_API_KEY=
```

---

## Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/slack/events` | POST | Slack event webhook — receives messages from `#coach` |
| `/cron/morning-briefing` | POST | Triggers news briefing → DM to Jonas |
| `/cron/weekly-review` | POST | Posts weekly review questions → `#coach` |
| `/health` | GET | Health check |

---

## Cron Schedule (cron-job.org)

| Job | URL | Schedule | Timezone |
|---|---|---|---|
| Morning briefing | `/cron/morning-briefing` | daily 07:00 | Europe/Zurich |
| Weekly review | `/cron/weekly-review` | Sunday 19:00 | Europe/Zurich |

---

## Slack App Setup

**OAuth & Permissions → Bot Token Scopes:**
- `chat:write`
- `channels:history`
- `channels:read`
- `im:write` ← required for DMs

**Event Subscriptions:**
- Request URL: `https://web-production-e88ec.up.railway.app/slack/events`
- Subscribe to: `message.channels`

---

## Morning Briefing Topics

Each briefing searches and summarises:

- 🌍 Geopolitics (Middle East + global)
- 🤖 AI & Tech
- 🗺️ GIS & Spatial Tech
- 🚀 Space Exploration
- 🇨🇭 Switzerland & Zurich

Delivered as a Slack DM, under 4000 characters.
