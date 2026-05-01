"""
#coach Slack Bot
Listens to messages in #coach and responds automatically via Claude.
Also sends morning briefings and weekly review prompts via Railway cron.
"""
import os
import json
import threading
import datetime
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
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

# Deduplicate Slack event deliveries — Slack retries if we're slow
processed_events = set()

SYSTEM_PROMPT = """You are Jonas's personal coach inside his #coach Slack channel.
## Your coaching personality
Encouraging but tough. You believe in Jonas and you show it — but you don't accept excuses
and you don't sugarcoat. When something is off, you say it clearly and move on.
When something is good, you acknowledge it and raise the bar. No bullshit, no lectures,
no sarcasm. Reasonable and human. Think of a coach who has seen it all and genuinely
wants Jonas to succeed.
If Jonas asks you something off-topic, just answer helpfully and briefly — you're his
coach, not a gatekeeper.
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
## Style
- Encouraging but no bullshit. No excuses accepted, but stay reasonable and human.
- Reference his specific situation — the prototype, the career inflection, the race.
- Short responses. He's busy.
- Use Slack markdown: *bold*, _italic_."""


# ── Helpers ──────────────────────────────────────────────────────────────────

def web_search(query: str) -> str:
    """Search the web via Serper and return a summary of top results with URLs."""
    response = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
        json={"q": query, "num": 5, "gl": "ch", "hl": "en"},
        timeout=10,
    )
    data = response.json()
    results = []
    for r in data.get("organic", [])[:5]:
        results.append(f"- {r.get('title', '')} ({r.get('link', '')}): {r.get('snippet', '')}")
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


def handle_coach_message(user_message: str, thread_ts: str):
    """Process coach response in background thread so Slack gets fast 200."""
    coach_reply = get_coach_response(user_message)
    send_slack_message(COACH_CHANNEL, coach_reply, thread_ts=thread_ts)


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


def get_air_quality() -> str:
    """Fetch latest sensor readings from openSenseMap (Habsburgstr, Zurich)."""
    try:
        req = urllib.request.Request(
            "https://api.opensensemap.org/boxes/69e699fa5a890400070d135e/sensors"
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        sensors = {s["title"]: s["lastMeasurement"]["value"] for s in data["sensors"]}
        pm10 = float(sensors.get("PM10", 0))
        pm25 = float(sensors.get("PM2.5", 0))
        temp = sensors.get("Temperatur", "?")
        humidity = sensors.get("rel. Luftfeuchte", "?")
        if pm10 < 10 and pm25 < 5:
            quality = "🟢 very clean"
        elif pm10 < 25:
            quality = "🟡 moderate"
        else:
            quality = "🔴 elevated"
        return f"PM10: {pm10} µg/m³ | PM2.5: {pm25} µg/m³ — {quality}\nTemp: {temp}°C | Humidity: {humidity}%"
    except Exception as e:
        return f"_Unavailable ({e})_"


def get_air_quality_spikes() -> str:
    """Check last 24h of PM10 readings for notable spikes."""
    try:
        now = datetime.datetime.utcnow()
        yesterday = now - datetime.timedelta(hours=24)
        from_date = yesterday.strftime("%Y-%m-%dT%H:%M:%SZ")
        to_date = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        url = (
            "https://api.opensensemap.org/boxes/69e699fa5a890400070d135e"
            f"/data/69e699fa5a890400070d135f?from-date={from_date}&to-date={to_date}&format=json"
        )
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=8) as resp:
            readings = json.loads(resp.read())
        spikes = [
            (r["createdAt"], float(r["value"]))
            for r in readings
            if float(r["value"]) > 15
        ]
        if spikes:
            peak = max(spikes, key=lambda x: x[1])
            time_str = peak[0][11:16]  # HH:MM from ISO timestamp
            return f"⚠️ Spike at ~{time_str} UTC: PM10 peaked at {peak[1]} µg/m³"
        return "No notable spikes in the last 24h"
    except Exception as e:
        return f"_Spike data unavailable ({e})_"


def get_todays_training() -> str:
    """Return today's training session based on the 28-week plan."""
    today = datetime.date.today()
    week1_start = datetime.date(2026, 4, 1)
    week_num = (today - week1_start).days // 7 + 1
    day = today.strftime("%A")

    long_runs = [
        16, 18, 20, 14,   # weeks 1–4
        22, 24, 26, 18,   # weeks 5–8
        26, 28, 30, 20,   # weeks 9–12
        28, 30, 32, 22,   # weeks 13–16
        30, 32, 32, 22,   # weeks 17–20
        29, 26, 22, 18,   # weeks 21–24
        16, 13, 10, 0,    # weeks 25–28 (taper + race)
    ]
    long_run_km = long_runs[week_num - 1] if 1 <= week_num <= len(long_runs) else 0

    race_notes = {
        6:  "🏁 SOLA Stafette this week (May 16) — ~13 km race leg, race hard",
        20: "🏁 Rheinfall-Lauf HM this week (~Aug 15) — race hard",
        28: "🏁 SwissCity Marathon Lucerne this week — race day Oct 25!",
    }
    race_note = race_notes.get(week_num, "")

    if day == "Wednesday":
        session = "Easy run — HR strictly <150, 8–10 km, flat route"
    elif day == "Friday":
        session = "Quality session — threshold intervals at 4:35–4:50/km. Eat beforehand."
    elif day == "Sunday":
        session = f"Long run — {long_run_km} km, easy effort, stay patient on pace"
    else:
        if day in ("Monday", "Tuesday"):
            next_session = "Wednesday (easy run)"
        elif day == "Thursday":
            next_session = "Friday (quality session)"
        else:  # Saturday
            next_session = "Sunday (long run)"
        session = f"Rest day — next up: {next_session}"

    result = f"Week {week_num}, {day}: {session}"
    if race_note:
        result += f"\n{race_note}"
    return result


# ── Morning briefing ──────────────────────────────────────────────────────────

def build_morning_briefing() -> str:
    """Search each topic in parallel and ask Claude to write the structured news briefing."""
    search_queries = {
        "geopolitics": "Middle East geopolitics news last 24 hours",
        "geopolitics_global": "major geopolitical developments Europe US Asia today",
        "ai_tech": "AI artificial intelligence tech news last 48 hours",
        "gis": "GIS geospatial QGIS WebGIS news 2026",
        "space": "space exploration NASA ESA SpaceX news today",
        "switzerland": "Switzerland Zurich news today",
        "weather": "Zurich weather today forecast",
        "pollen": "pollen forecast Zurich today meteoswiss",
    }

    # Run all searches + sensor calls in parallel
    searches = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_key = {executor.submit(web_search, q): k for k, q in search_queries.items()}
        future_to_key[executor.submit(get_air_quality)] = "_air_quality"
        future_to_key[executor.submit(get_air_quality_spikes)] = "_air_spikes"
        for future in as_completed(future_to_key):
            key = future_to_key[future]
            try:
                searches[key] = future.result()
            except Exception as e:
                searches[key] = f"_Error: {e}_"

    air_quality = searches.pop("_air_quality", "_Unavailable_")
    air_quality_spikes = searches.pop("_air_spikes", "_Unavailable_")
    training = get_todays_training()

    search_context = "\n\n".join(
        f"### {topic.upper()} SEARCH RESULTS:\n{results}"
        for topic, results in searches.items()
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1800,
        messages=[
            {
                "role": "user",
                "content": (
                    "You are a personal briefing agent. Write a concise morning briefing. "
                    "Use Slack markdown (*bold*, _italic_). Format links as <url|link text>.\n\n"

                    "🌤️ *Zurich Weather*\n"
                    "From the weather search results: current temp, today's high/low, rain chance. 2 lines max.\n\n"

                    f"🌫️ *Air Quality — Habsburgstr*\n"
                    f"{air_quality}\n"
                    f"{air_quality_spikes}\n\n"

                    "🌿 *Pollen — Zurich*\n"
                    "From the pollen search results: active pollen types and intensity today. 1–2 lines.\n\n"

                    "🌍 *Geopolitics*\n"
                    "Middle East last 24–48h + other major developments (Europe, US, Asia). "
                    "Factual, no opinion. 3–5 key points. Link per item.\n\n"

                    "🤖 *AI & Tech*\n"
                    "New models, tools, launches, industry moves. Skip hype, prioritize signal. "
                    "2–3 items. Link per item.\n\n"

                    "🗺️ *GIS & Spatial Tech*\n"
                    "QGIS, open source geo tools, spatial data, WebGIS, geospatial industry. "
                    "1–2 items if available. Link per item.\n\n"

                    "🚀 *Space Exploration*\n"
                    "Missions, launches, discoveries, agency news. 1–2 items. Link per item.\n\n"

                    "🇨🇭 *Switzerland & Zurich*\n"
                    "Local news — politics, economy, city developments. 2–3 items. Link per item.\n\n"

                    f"🏃 *Today's Training*\n"
                    f"{training}\n\n"

                    "End with one sentence: the single most important thing to be aware of today.\n\n"
                    "Keep the full message under 4500 characters.\n\n"
                    f"{search_context}"
                ),
            }
        ],
    )
    return response.content[0].text


# ── Routes ────────────────────────────────────────────────────────────────────

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
    event_id = data.get("event_id", "")

    # Deduplicate — Slack retries if response is slow
    if event_id and event_id in processed_events:
        return jsonify({"ok": True})
    if event_id:
        processed_events.add(event_id)

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
        thread_ts = event.get("thread_ts") or event.get("ts")
        # Process in background so Slack gets immediate 200
        t = threading.Thread(target=handle_coach_message, args=(user_message, thread_ts))
        t.daemon = True
        t.start()

    return jsonify({"ok": True})


def run_morning_briefing():
    """Build and send the briefing in a background thread."""
    briefing = build_morning_briefing()
    dm_channel = open_dm_channel(JONAS_USER_ID)
    send_slack_message(dm_channel, briefing)


@app.route("/cron/morning-briefing", methods=["POST"])
def morning_briefing():
    """Called by Railway cron — returns 200 immediately, builds briefing in background."""
    t = threading.Thread(target=run_morning_briefing)
    t.daemon = True
    t.start()
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
