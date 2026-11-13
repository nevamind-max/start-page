"""start.metakultura.store — лендинг для артистів + приймач заявок у Telegram."""
import html
import os
import time
from collections import defaultdict, deque

import requests
from flask import Flask, jsonify, request, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_TOKEN = os.environ.get("LEAD_BOT_TOKEN", "")
CHAT_ID = os.environ.get("LEAD_CHAT_ID", "")

app = Flask(__name__, static_folder=os.path.join(BASE_DIR, "static"), static_url_path="/static")

# не більше 5 заявок з однієї IP за 10 хвилин
_hits = defaultdict(deque)
LIMIT, WINDOW = 5, 600

FIELDS = {"name": 120, "telegram": 120, "link": 300, "merch": 80,
          "tariff": 80, "message": 2000, "source": 300}


def client_ip():
    fwd = request.headers.get("X-Forwarded-For", "")
    return fwd.split(",")[0].strip() if fwd else (request.remote_addr or "?")


def rate_limited(ip):
    now = time.time()
    q = _hits[ip]
    while q and now - q[0] > WINDOW:
        q.popleft()
    if len(q) >= LIMIT:
        return True
    q.append(now)
    return False


@app.get("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/favicon.ico")
def favicon():
    return send_from_directory(os.path.join(BASE_DIR, "static"), "favicon.ico",
                               mimetype="image/vnd.microsoft.icon")


@app.get("/apple-touch-icon.png")
def apple_touch_icon():
    return send_from_directory(os.path.join(BASE_DIR, "static"), "apple-touch-icon.png")


@app.get("/health")
def health():
    return {"ok": True, "telegram_configured": bool(BOT_TOKEN and CHAT_ID)}


@app.post("/api/lead")
def lead():
    data = request.get_json(silent=True) or {}
    if data.get("website"):  # пастка для ботів
        return jsonify(ok=True)
    clean = {k: str(data.get(k, "")).strip()[:n] for k, n in FIELDS.items()}
    if not clean["name"] or not clean["telegram"]:
        return jsonify(ok=False, error="required"), 400
    if rate_limited(client_ip()):
        return jsonify(ok=False, error="rate"), 429

    e = lambda s: html.escape(s) if s else "—"
    text = (
        "🎸 <b>Нова заявка зі start.metakultura.store</b>\n\n"
        f"👤 <b>Проєкт:</b> {e(clean['name'])}\n"
        f"✈️ <b>Telegram:</b> {e(clean['telegram'])}\n"
        f"🔗 <b>Посилання:</b> {e(clean['link'])}\n"
        f"👕 <b>Мерч:</b> {e(clean['merch'])}\n"
        f"💼 <b>Тариф:</b> {e(clean['tariff'])}\n"
        f"💬 <b>Коментар:</b> {e(clean['message'])}\n\n"
        f"<i>Джерело: {e(clean['source'])}</i>"
    )
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=10,
        )
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        app.logger.error("Telegram send failed: %s", exc)
        return jsonify(ok=False, error="send"), 502
    return jsonify(ok=True)
