# `health-export/v1` payload

The only format the app sends. One request per day (today, plus yesterday once after midnight),
`POST` to the configured URL exactly as entered.

## Request

| Header | Value |
| --- | --- |
| `Content-Type` | `application/json` |
| `Authorization` | `Bearer <token>` (only if a token is set) |
| `Idempotency-Key` | SHA-256 hex of the body. An identical retry carries the same key. |

Redirects are not followed (the token is never sent to another host). Any 2xx = delivered.
Other responses are retried with backoff (1, 2, 4 … min, max 6 h); 4xx except 408/429 waits 6 h or a manual sync.
A later payload for the same date replaces an undelivered one, so receivers should treat each request as
"the full current state of that date" and overwrite.

## Body

```json
{
  "schema": "health-export/v1",
  "date": "2026-11-01",
  "timezone": "Asia/Shanghai",
  "utc_offset": "+08:00",
  "generated_at": "2026-11-01T18:30:02.114+08:00",
  "device_id": "UUID, random per install",
  "app": { "bundle_id": "cn.miaclass.health", "version": "0.1.0" },
  "summary": { "steps": 8821, "resting_hr": 58, "sleep_min": 412, "stand_hours": 8, "...": "..." },
  "detail": {
    "stood_hours": ["09", "11"], "idle_hours": ["10"],
    "workouts": [{ "type": "walking", "start": "14:53", "end": "16:02", "min": 69, "kcal": 375, "avg_hr": 138,
                   "km": 6.02, "source": "Apple Watch", "bundle": "com.apple.health.XXXX" }],
    "sleep_stages": [{ "stage": "core", "start": "ISO-8601", "end": "ISO-8601" }]
  },
  "samples": {
    "heart_rate": [{ "t": "ISO-8601", "bpm": 72 }],
    "steps": [{ "start": "ISO-8601", "end": "ISO-8601", "count": 512, "source": "KS Fit", "bundle": "com.kingsmith.xxx", "device": "other" }],
    "distance": [{ "start": "ISO-8601", "end": "ISO-8601", "km": 0.412, "source": "Apple Watch", "bundle": "com.apple.health.XXXX", "device": "watch" }]
  },
  "trigger": { "kind": "wake", "wake_id": "abc123" },
  "location": { "lat": 22.957, "lon": 113.356, "accuracy_m": 65, "fix_time": "ISO-8601", "source": "update" }
}
```

- Keys are omitted when there is no data or the group is switched off; absent ≠ 0.
- `samples` only with Include Raw Samples (附带原始样本): `heart_rate` with the heart group, `steps` / `distance` with the steps group. Step and distance samples come from every source, not de-duplicated: `source` is the app's display name, `bundle` its bundle id (`com.apple.*` = Apple), `device` is `watch` or `phone` for Apple's own sensors, `other` for anything written by a third-party app (treadmill, scale, …). `summary.steps` / `distance_km` stay Apple Health's merged totals (its source priority); de-duplicate from `samples` if you want your own rule (e.g. treadmill app > Watch > iPhone).
- `detail.workouts[].source` / `bundle` name the app that saved the workout (added in 1.1); `workout_*` totals count all sources.
- `trigger` only on an on-demand refresh (按需刷新, added in 1.1): your server POSTed the relay's wake URL, optionally with `{"wake_id": "..."}`, and this payload is the answer. Match `trigger.wake_id` to know the refresh arrived. Yesterday may be sent in the same run with the same `trigger`. Best effort: iOS may delay or drop silent pushes (low power, app force-quit, throttling), so time out after ~60 s. If the push arrives while Health data is locked (phone locked for a while), the app answers on the next run that can read it (usually the next unlock), still with that `wake_id` (`trigger.deferred: true`) — late, not lost.
- `origin: "watch"` (planned for 1.2, opt-in under Settings → Upload from Apple Watch): the payload was sent by the Apple Watch app, which can read the watch's Health data while the iPhone is locked. It holds only what the watch has — no iPhone-only sources (treadmill apps, phone-only steps), no `location` — so **merge it into the day, don't overwrite**: take the larger day counters (`steps`, `active_kcal`, …), the smaller `hr_min`, the union of `samples` / workouts / stood hours, and the newer point readings. A watch run may answer a refresh too (same `trigger.wake_id`). Absent `origin` = the iPhone.
- `location` only with Location Sync (位置同步) on (3 decimals ≈ 100 m, latest fix only).
- A connection test sends `{"schema":"health-export/v1","test":true,...}`; reply 2xx and store nothing.

### summary keys

| Key | Unit | Group | Notes |
| --- | --- | --- | --- |
| `steps` | count | steps | HealthKit de-duplicated sum, all sources |
| `distance_km`, `flights` | km, floors | steps | |
| `resting_hr` | bpm | heart | latest of the day |
| `hr_avg`, `hr_min`, `hr_max` | bpm | heart | time-weighted mean (gap to next sample, capped 10 min) / min / max |
| `hrv_ms` | ms | heart | SDNN, mean |
| `walking_hr` | bpm | heart | |
| `spo2_pct` | % | vitals | mean |
| `resp_rate` | /min | vitals | sleep window [date−6h, date+12h) |
| `wrist_temp_c` | °C | vitals | sleep window, absolute |
| `vo2max` | ml/kg·min | vitals | only after outdoor walk/run/hike |
| `hr_recovery` | bpm | vitals | only after a workout |
| `sleep_min`, `sleep_start`, `sleep_end` | min, ISO | sleep | Apple Watch stages starting in [date−6h, date+12h), awake excluded |
| `exercise_min` | min | activity | Apple Exercise Time |
| `active_kcal`, `move_goal_kcal` | kcal | activity | Move ring |
| `exercise_goal_min` | min | activity | |
| `stand_hours`, `stand_goal_hours`, `stand_min` | h, h, min | activity | |
| `workout_count`, `workout_min`, `workout_kcal` | –, min, kcal | workouts | |
| `daylight_min` | min | daylight | |

Breaking changes get a new `schema` value; new optional keys may be added within v1.
