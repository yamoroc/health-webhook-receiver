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
- `metrics`, `latest`, `catalog` only with the More Health Data group (更多健康数据, added in 1.2, iPhone only — watch payloads never carry them, so keep the phone's when merging). See below.
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

### More Health Data (1.2)

Every other HealthKit type the user has (weight, resting energy, mobility, noise, nutrition, symptoms, ECG …). Sparse: a type appears only on days it has samples.

```json
"metrics": {
  "basal_kcal":       { "unit": "kcal", "n": 288, "sum": 1702.4 },
  "walking_speed":    { "unit": "m/s", "n": 12, "avg": 1.31, "min": 1.12, "max": 1.52, "last": 1.4, "last_at": "ISO-8601" },
  "high_heart_rate_event": { "n": 1, "times": ["ISO-8601"], "values": { "0": 1 } },
  "mindful_session":  { "n": 2, "times": ["ISO-8601", "ISO-8601"], "values": { "0": 2 }, "minutes": 12 },
  "ecg":              { "n": 1, "times": ["ISO-8601"], "classification": ["sinus_rhythm"], "avg_hr": 68 }
},
"latest": {
  "body_mass": { "value": 74.1, "unit": "kg", "at": "ISO-8601", "source": "Health" }
},
"catalog": {
  "body_mass":    { "first": "2016-06-13", "last": "2026-11-10" },
  "dietary_kcal": { "first": "2020-02-14", "last": "2020-07-10" }
}
```

- **Quantity types** — cumulative (energy, distances, nutrition …): `sum` (HealthKit de-duplicated across sources) and `n` samples; discrete (body measurements, speeds, dB …): `avg` / `min` / `max` over all samples of the day, `last` + `last_at`. Units are fixed per key (`unit`); percentages are 0–100.
- **Category types** (events, symptoms, cycle tracking): `n`, start `times` (first 50), `values` = count per HealthKit raw value (severity, flow level …), `minutes` = summed duration when samples have one.
- **Others**: `ecg` (`classification`, `avg_hr`), `state_of_mind` (`valence_avg`, −1…1), `gad7` / `phq9` (`last_score`), `audiogram` (count and times only).
- **`heartbeat_series`** (beat-to-beat recordings, e.g. the Watch's background HRV readings): `{n, times, series, rmssd_avg_ms, rmssd_clean_median_ms}`. Each `series[]` item is `{start, beats, rr_ms, rmssd_ms, rmssd_clean_ms, artifacts, gaps, avg_hr}`: `rr_ms` are the RR intervals in milliseconds (rounded), skipping any interval across a gap the Watch flagged; `rmssd_ms` is computed only from adjacent unbroken intervals; `avg_hr` = 60000 / mean RR. `rmssd_ms` and `rmssd_avg_ms` (mean of the day's per-series RMSSD) are raw — no artifact filtering; a missed beat (one interval about twice its neighbours) can inflate a reading several-fold, which is common in sleep. **Prefer `rmssd_clean_ms`**: the same RMSSD after dropping intervals outside 300–2000 ms or more than 20% away from the median of the 5 intervals on each side, using only adjacent kept pairs (absent when fewer than 10 pairs remain). `artifacts` is the number of intervals dropped. `gaps` (omitted when empty) lists the `rr_ms` indices that follow a Watch-flagged gap, so a consumer can recompute without pairing across a gap. Day level: `rmssd_clean_median_ms` is the median of the day's `rmssd_clean_ms`.
- Workout routes (GPS) are not exported.
- **`latest`**: newest sample ever (up to the end of `date`) of slow-changing measurements — `body_mass`, `height`, `body_mass_index`, `body_fat_pct`, `lean_body_mass`, `waist_circumference`, `walking_steadiness_pct`, `cycling_ftp`, `bp_systolic`, `bp_diastolic`, `vo2max`. Use it when the day itself has no reading.
- **`catalog`**: every type with any data, first/last sample date. Recomputed at most once a day (cached copy otherwise), so a type that stopped being recorded years ago is visible here without appearing in `metrics`.
- Keys and the full list live in `HealthSync/HealthMetrics.swift`; new keys may be added within v1.

Breaking changes get a new `schema` value; new optional keys may be added within v1.
