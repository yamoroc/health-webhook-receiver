#!/usr/bin/env python3
"""Minimal receiver for the `health-export/v1` webhook (Health Data Webhook Sync for iOS).

Stores the latest payload per day as DATA_DIR/<date>.json and appends a delivery log.
Python 3.9+ standard library only.

Environment:
  TOKEN     Bearer token the app sends (strongly recommended; empty = no auth)
  PORT      listen port (default 8080)
  HOST      listen address (default 0.0.0.0)
  DATA_DIR  where files go (default ./data)
  INGEST_PATH  URL path to accept (default /ingest)
"""
import hmac
import json
import os
import re
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ.get("TOKEN", "")
PORT = int(os.environ.get("PORT", "8080"))
HOST = os.environ.get("HOST", "0.0.0.0")
DATA_DIR = os.path.abspath(os.environ.get("DATA_DIR", "data"))
PATH = os.environ.get("INGEST_PATH", "/ingest")
MAX_BODY = 10 * 1024 * 1024
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

os.makedirs(DATA_DIR, exist_ok=True)
LOG = os.path.join(DATA_DIR, "deliveries.jsonl")
LAST_PHONE = os.path.join(DATA_DIR, "last-phone.json")
lock = threading.Lock()


def parse_time(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def load_last_phone():
    try:
        with open(LAST_PHONE, encoding="utf-8") as f:
            return json.load(f).get("generated_at")
    except (OSError, ValueError):
        return None


# Newest generated_at of an iPhone payload, returned as `last_phone_at` (see docs/payload-v1.md, Response):
# the Apple Watch app slows its scheduled uploads while the iPhone is uploading.
last_phone_at = load_last_phone()


def load_seen():
    seen = set()
    if os.path.exists(LOG):
        with open(LOG, encoding="utf-8") as f:
            for line in f:
                try:
                    k = json.loads(line).get("key")
                except ValueError:
                    continue
                if k:
                    seen.add(k)
    return seen


seen = load_seen()


class Handler(BaseHTTPRequestHandler):
    server_version = "health-webhook-receiver/1"

    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/healthz":
            return self.reply(200, {"status": "ok"})
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        global last_phone_at
        if self.path.split("?")[0] != PATH:
            return self.reply(404, {"error": "not found"})
        if TOKEN and not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {TOKEN}"):
            return self.reply(401, {"error": "unauthorized"})
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return self.reply(413 if length > MAX_BODY else 400, {"error": "bad length"})
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError:
            return self.reply(400, {"error": "invalid JSON"})
        if not isinstance(body, dict) or body.get("schema") != "health-export/v1":
            return self.reply(400, {"error": "unknown schema"})
        if body.get("test") is True:
            return self.reply(200, {"status": "ok", "test": True})
        date = str(body.get("date", ""))
        if not DATE_RE.match(date):
            return self.reply(400, {"error": "bad date"})

        key = self.headers.get("Idempotency-Key", "")
        with lock:
            duplicate = bool(key) and key in seen
            if not duplicate:
                # Each request is the full current state of that day: overwrite.
                # Apple Watch payloads ("origin": "watch") hold only the watch's data,
                # so they go to their own file instead of replacing the iPhone's.
                name = f"{date}.watch.json" if body.get("origin") == "watch" else f"{date}.json"
                tmp = os.path.join(DATA_DIR, f".{name}.tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(body, f, ensure_ascii=False, indent=2)
                os.replace(tmp, os.path.join(DATA_DIR, name))
                if key:
                    seen.add(key)
                gen = body.get("generated_at")
                t = parse_time(gen) if body.get("origin") != "watch" and gen else None
                prev = parse_time(last_phone_at) if last_phone_at else None
                if t and t.tzinfo and (prev is None or not prev.tzinfo or t > prev):
                    last_phone_at = gen
                    with open(LAST_PHONE, "w", encoding="utf-8") as f:
                        json.dump({"generated_at": gen}, f)
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "date": date, "origin": body.get("origin", "phone"), "key": key, "duplicate": duplicate,
                    "summary_keys": len(body.get("summary") or {}),
                    "has_location": "location" in body, "has_samples": "samples" in body,
                }) + "\n")
        reply = {"status": "ok", "duplicate": duplicate}
        if last_phone_at:
            reply["last_phone_at"] = last_phone_at
        self.reply(200, reply)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))


if __name__ == "__main__":
    if not TOKEN:
        print("warning: TOKEN is empty, anyone who can reach this port can write data", file=sys.stderr)
    print(f"health-export/v1 receiver on http://{HOST}:{PORT}{PATH} -> {DATA_DIR}", file=sys.stderr)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
