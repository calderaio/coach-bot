"""
#coach Slack Bot
Listens to messages in #coach and responds automatically via Claude.
Also sends morning briefings and weekly review prompts via Railway cron.
"""

import os
import json
import requests
from flask import Flask, request, jsonify
import anthropic
import urllib.request
import urllib.parse

app = Flask(__name__)

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]
SERPER_API_KEY = os.environ["SERPER_API_KEY"]

COACH_CHANNEL = "C0ARJPL7P0U"
JONAS_USER_ID = "U0ARF3U0TTL"

SYSTEM_PROMPT = """You are Jonas's personal coach inside his #coach Slack channel.
You respond to two types of messages:

1. RUN DEBRIEFS — Jonas pastes run data (from Strava, Garmin, or plain text).
   Analyse across: effort vs target, HR discipline, pace & elevation (use GAP if available),
   splits, what it means for fitness, and one focus point for the next session.
   Be direct. If HR was too high, say so. Keep it under 300 words.

2. WEEKLY REVIEW RESPONSES — Jonas answers your Sunday evening questions about
   his week. Respond with honest, pointed feedback on each answer. No fluff.

## Jonas's profile
- M40, Zürich. Developer and GIS unit lead at a Swiss company.
- Building a WebGIS prototype for communes (due May 2026), considering going independent.
- Marathon: SwissCity Lucerne, 25 Oct 2026. Goal: sub-3:30 (4:58/km).
- VO2max ~47.5. Threshold: 4:35–4:50/km. Easy HR: strictly <150.
- Weakness: easy runs drift too fast, HR hits 155–165 on hills. Needs flat routes.
- Runs Wed (easy) / Fri (quality) / Sun (long). Long run always highest priority.
- Plan: 28 weeks from April 1, 2026. Drop-back every 4th week.
- Built-in races: Zürich HM Apr 12, SOLA Stafette May 16, Rheinfall-Lauf HM ~Aug 15.
- Habits to track gently (not every message): drinking, smoking, relationship with partner.

## Coaching style
- Sharp, honest, no generic encouragement.
- Reference his specific situation — the prototype, the career inflection, the race.
- Short responses. He's busy.
- Use Slack markdown: *bold*, _italic_."""


def web_search(query: str) -> str:
    """Search the web via Serper and return a summary of top results."""
    response = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
        json={"q": query, "num": 5, "gl": "ch", "hl": "en"},
        timeout=10,
    )
    data = response.json()
    results = []
    for r in data.get("organic", [])[:5]:
        results.append(f"- {r.get('title', '')}: {r.get('snippet', '')}")
    return "\n".join(results) if results else "No results found."


def send_slack_message(channel: str, text: str, thread_ts: str = None):
    url = "https://slack.com/api/chat.postMessage"
    payload = {"channel": channel, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts

    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {SLACK_BOT_TOKEN}")
    req.add_header("Content-Type", "application/json")

    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def get_coach_response(user_message: str) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


def open_dm_channel(user_id: str) -> str:
    """Open a DM channel with a user and return the channel ID."""
    url = "https://slack.com/api/conversations.open"
    payload = json.dumps({"users": user_id}).encode()
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Authorization", f"Bearer {SLACK_BOT_TOKEN}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    return data["channel"]["id"]


def build_morning_briefing() -> str:
    """Search each topic and ask Claude to write the structured news briefing."""
    searches = {
        "geopolitics": web_search("Middle East geopolitics news last 24 hours"),
        "geopolitics_global": web_search("major geopolitical developments Europe US Asia today"),
        "ai_tech": web_search("AI artificial intelligence tech news last 48 hours"),
        "gis": web_search("GIS geospatial QGIS WebGIS news 2026"),
        "space": web_search("space exploration NASA ESA SpaceX news today"),
        "switzerland": web_search("Switzerland Zurich news today"),
    }

    search_context = "\n\n".join(
        f"### {topic.upper()} SEARCH RESULTS:\n{results}"
        for topic, results in searches.items()
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[
            {
                "role": "user",
                "content": (
                    "You are a personal briefing agent. Write a concise morning briefing based on the search results below. "
                    "Use this exact structure with Slack markdown (*bold*, _italic_):\n\n"
                    "🌍 *Geopolitics*\n"
                    "Focus on Middle East last 24-48h + other major developments (Europe, US, Asia). Factual, no opinion. 3-5 key points.\n\n"
                    "🤖 *AI & Tech*\n"
                    "New models, tools, product launches, industry moves. Skip hype, prioritize signal. 2-3 items.\n\n"
                    "🗺️ *GIS & Spatial Tech*\n"
                    "QGIS, open source geo tools, spatial data, WebGIS, geospatial industry. 1-2 items if available.\n\n"
                    "🚀 *Space Exploration*\n"
                    "Missions, launches, discoveries, agency news. 1-2 items.\n\n"
                    "🇨🇭 *Switzerland & Zurich*\n"
                    "Local news — politics, economy, city developments. 2-3 items.\n\n"
                    "End with one sentence: the single most important thing to be aware of today across all topics.\n\n"
                    "Keep the full message under 4000 characters.\n\n"
                    f"{search_context}"
                ),
            }
        ],
    )
    return response.content[0].text


WEEKLY_REVIEW_PROMPT = """Good evening. Weekly review time — answer these honestly:

1. *Runs completed* — which sessions did you do, skip, or modify? Why?
2. *HR discipline* — how well did you stay under 150 on easy runs?
3. *Energy & recovery* — sleep, stress, how the body feels going into next week?
4. *Habits* — drinking, smoking, anything worth noting?
5. *Work/life* — prototype progress, anything weighing on you?

Keep it brief. I'll give you feedback on each."""


@app.route("/slack/events", methods=["POST"])
def slack_events():
    data = request.json

    # Slack URL verification handshake
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data["challenge"]})

    event = data.get("event", {})

    # Only respond to real messages from Jonas in #coach — ignore bot messages
    if (
        event.get("type") == "message"
        and event.get("user") == JONAS_USER_ID
        and event.get("channel") == COACH_CHANNEL
        and not event.get("bot_id")
        and not event.get("subtype")
    ):
        user_message = event.get("text", "").strip()
        if not user_message:
            return jsonify({"ok": True})

        coach_reply = get_coach_response(user_message)
        thread_ts = event.get("thread_ts") or event.get("ts")
        send_slack_message(COACH_CHANNEL, coach_reply, thread_ts=thread_ts)

    return jsonify({"ok": True})


@app.route("/cron/morning-briefing", methods=["POST"])
def morning_briefing():
    """Called by Railway cron — sends news briefing as a DM to Jonas."""
    briefing = build_morning_briefing()
    dm_channel = open_dm_channel(JONAS_USER_ID)
    send_slack_message(dm_channel, briefing)
    return jsonify({"ok": True})


@app.route("/cron/weekly-review", methods=["POST"])
def weekly_review():
    """Called by Railway cron on Sunday evenings — posts weekly review questions."""
    send_slack_message(COACH_CHANNEL, WEEKLY_REVIEW_PROMPT)
    return jsonify({"ok": True})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)
