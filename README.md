# health-webhook-receiver

A tiny, dependency-free receiver for **Health Data Webhook Sync** (iOS). The app POSTs one `health-export/v1` JSON document per day to your HTTPS URL. This server checks the Bearer token, writes the latest version of each day to `data/<date>.json`, and logs every delivery to `data/deliveries.jsonl`.

It is one Python file (standard library only, Python 3.9+). Use it as is, or read it as a reference for the contract and plug the same logic into your own stack (n8n, Home Assistant, a database, …).

## Run

```bash
# plain Python
TOKEN=change-me python3 receiver.py            # listens on :8080, path /ingest

# Docker
docker build -t health-webhook-receiver .
docker run -d --name health-receiver -p 8080:8080 \
  -e TOKEN=change-me -v "$PWD/data:/data" health-webhook-receiver
```

| Variable | Default | |
| --- | --- | --- |
| `TOKEN` | empty | Bearer token, same as in the app. Empty disables auth (don't). |
| `PORT` | `8080` | |
| `HOST` | `0.0.0.0` | |
| `INGEST_PATH` | `/ingest` | |
| `DATA_DIR` | `./data` (`/data` in Docker) | |

`GET /healthz` returns `{"status":"ok"}`.

## HTTPS is required

The app only sends to `https://` URLs and refuses redirects. Put the receiver behind a reverse proxy with a valid certificate, for example Caddy:

```
health.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

Then in the app: **Settings → URL** `https://health.example.com/ingest`, **Token** the same `TOKEN`, then **Test Connection**. Tunnels such as Cloudflare Tunnel or Tailscale Funnel work too.

## Try it

```bash
# connection test from the app: 200, nothing stored
curl -X POST http://127.0.0.1:8080/ingest -H 'Authorization: Bearer change-me' \
  -d '{"schema":"health-export/v1","test":true}'

# a day
curl -X POST http://127.0.0.1:8080/ingest -H 'Authorization: Bearer change-me' \
  -H 'Idempotency-Key: demo-1' \
  -d '{"schema":"health-export/v1","date":"2026-11-01","summary":{"steps":8421,"resting_hr":58}}'
```

## The contract in short

Full field list: [docs/payload-v1.md](docs/payload-v1.md).

Request: `POST`, `Content-Type: application/json`, `Authorization: Bearer <token>` (if set), `Idempotency-Key: <sha256 of body>`.

```json
{
  "schema": "health-export/v1",
  "date": "2026-11-01",
  "timezone": "America/Los_Angeles",
  "utc_offset": "-07:00",
  "generated_at": "2026-11-01T21:04:11.120-07:00",
  "device_id": "random UUID per install",
  "app": { "bundle_id": "cn.miaclass.health", "version": "1.0" },
  "summary": { "steps": 8421, "resting_hr": 58, "hrv_ms": 47, "sleep_min": 432, "…": "…" },
  "detail": { "workouts": [ … ], "stood_hours": [ … ] },
  "samples": { "…": "optional, only if enabled in the app" },
  "location": { "…": "optional, only if enabled in the app" }
}
```

- **Overwrite per date.** The app sends the same day again as more data arrives (and on backfill). Each request is the full current state of that day, so keep the newest one.
- **Any 2xx means delivered.** Anything else is retried with backoff (1, 2, 4 … minutes, up to 6 h). 4xx other than 408/429 waits 6 h, so fix auth or the URL and the app will catch up.
- **Test requests** (`"test": true`) must get a 2xx and should store nothing.
- Fields only present when their group is switched on in the app; missing means "no data or not shared", not zero.
- Idempotency-Key repeats mean a retry of a body you already have; answering 2xx again is correct.

## License

MIT
