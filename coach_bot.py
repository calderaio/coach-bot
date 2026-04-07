"""
#coach Slack Bot
Listens to messages in #coach and responds automatically via Claude.
"""

import os
import json
from flask import Flask, request, jsonify
import anthropic
import urllib.request
import urllib.parse

app = Flask(__name__)

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]

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


def send_slack_message(channel: str, text: str, thread_ts: str = None):
    url = "https://slack.com/api/chat.postMessage"
    payload = {"channel": channel, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts

    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {SLACK_BOT_TOKEN}")
    req.add_header("Content-Type", "application/json")

    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def get_coach_response(user_message: str) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


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

        # Get Claude's response
        coach_reply = get_coach_response(user_message)

        # Reply in the same thread if it's a threaded message, otherwise in channel
        thread_ts = event.get("thread_ts") or event.get("ts")
        send_slack_message(COACH_CHANNEL, coach_reply, thread_ts=thread_ts)

    return jsonify({"ok": True})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)
