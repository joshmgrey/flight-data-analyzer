# Flight Data Analyzer: Interface Control Document

| | |
|---|---|
| Document | FDA-ICD-001 |
| Version | 0.1 (draft) |
| Date | 2026-10-27 |
| Author | Joshua Grey |
| Related | [Requirements](REQUIREMENTS.md) · [RVTM](RVTM.md) |

## 1. Scope

This document defines the three interfaces of Flight Data Analyzer (FDA):

| ID | Interface | Provider → consumer |
|---|---|---|
| IF-1 | OpenSky Network REST API, `/states/all` | OpenSky → `fda.ingest` |
| IF-2 | PostgreSQL schema (`poll_runs`, `state_vectors`) | `fda.ingest` → `fda.analyze`, `fda.health` |
| IF-3 | Process interface: environment, exit codes, log lines | `fda.ingest` ↔ systemd / cron / `scripts/*.sh` |

```
 OpenSky REST ──IF-1──▶ fda.ingest ──IF-2──▶ PostgreSQL ──IF-2──▶ fda.analyze ─▶ Markdown report
   (HTTPS/JSON)          ▲    │                                  └─▶ fda.health ◀─ healthcheck.sh
                         │    └─IF-3 (exit code, stdout)─▶ journald ─▶ inspect_logs.sh
              systemd timer (IF-3: EnvironmentFile /etc/fda/fda.env)
```

The OpenSky facts in section 2 come from the public OpenSky REST API documentation and a live
response captured on 2026-10-27 (`tests/fixtures/opensky_states_sample.json`). OpenSky may
change its API; FDA detects incompatible changes as `schema_error` (FDA-008).

## 2. IF-1: OpenSky Network REST API

### 2.1 Overview

| Property | Value |
|---|---|
| Direction | Pull; FDA initiates every request |
| Transport | HTTPS (TLS), HTTP/1.1 |
| Encoding | JSON (UTF-8) |
| Frequency | One request per poll; nominally every 300 s (FDA-003) |
| Timeout | 20 s per attempt; up to 3 attempts per poll (FDA-006) |
| Terms | Non-commercial research and education use; cite the OpenSky Network |

### 2.2 Request

`GET https://opensky-network.org/api/states/all`

| Query parameter | Type | FDA value | Meaning |
|---|---|---|---|
| `lamin` | float | 39.05 | Southern latitude bound, decimal degrees (WGS-84) |
| `lomin` | float | -75.05 | Western longitude bound |
| `lamax` | float | 39.85 | Northern latitude bound |
| `lomax` | float | -74.10 | Eastern longitude bound |
| `extended` | int | 1 | Include the aircraft `category` field (index 17) |

| Header | Value |
|---|---|
| `User-Agent` | `flight-data-analyzer/0.1 (non-commercial portfolio project)` |
| `Authorization` | `Bearer <token>`, only when authenticated (section 2.3) |

### 2.3 Authentication

Anonymous by default. When `OPENSKY_CLIENT_ID` and `OPENSKY_CLIENT_SECRET` are set, FDA
obtains a token with the OAuth2 client-credentials grant:

`POST https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token`
with form fields `grant_type=client_credentials`, `client_id`, `client_secret`. The JSON reply
contains `access_token` and `expires_in` (seconds). FDA caches the token until 30 s before
expiry (FDA-009). A non-200 reply is an upstream error.

### 2.4 Response body

```json
{"time": 1793144103, "states": [["adda1e", "AAL2641 ", "United States", 1793144103, 1793144103,
  -74.8703, 39.2814, 2994.66, false, 152.85, 343.58, -2.6, null, 3147.06, "4145", false, 0, 1]]}
```

| Field | Type | Notes |
|---|---|---|
| `time` | integer | Response time, Unix seconds (UTC). Required; stored as `api_time`. |
| `states` | array of arrays, or `null` | `null` means no aircraft in the box (FDA-011). |

Each state array, by index:

| Idx | Name | JSON type | Units | Null? | DB column | Notes |
|---|---|---|---|---|---|---|
| 0 | icao24 | string | – | no | `icao24` | 24-bit ICAO address, 6 hex digits; lower-cased. Invalid → row rejected. |
| 1 | callsign | string | – | yes | `callsign` | 8 chars, space-padded; trimmed, empty → null. |
| 2 | origin_country | string | – | yes | `origin_country` | Inferred from the ICAO address block. |
| 3 | time_position | integer | Unix s | yes | `time_position` | Time of last position update. |
| 4 | last_contact | integer | Unix s | no | `last_contact` | Time of last message of any kind. Missing → row rejected. |
| 5 | longitude | float | deg | yes | `longitude` | WGS-84. |
| 6 | latitude | float | deg | yes | `latitude` | WGS-84. |
| 7 | baro_altitude | float | m | yes | `baro_altitude_m` | Barometric altitude. Null when on ground. |
| 8 | on_ground | boolean | – | no | `on_ground` | From surface-position messages. |
| 9 | velocity | float | m/s | yes | `velocity_mps` | Ground speed. |
| 10 | true_track | float | deg | yes | `true_track_deg` | Clockwise from north. |
| 11 | vertical_rate | float | m/s | yes | `vertical_rate_mps` | Positive is climbing. |
| 12 | sensors | int array | – | yes | not stored | Receiver IDs; null unless requested. |
| 13 | geo_altitude | float | m | yes | `geo_altitude_m` | Geometric (GNSS) altitude. |
| 14 | squawk | string | – | yes | `squawk` | Mode A transponder code, 4 octal digits. |
| 15 | spi | boolean | – | yes | `spi` | Special position identification ("ident"). |
| 16 | position_source | integer | enum | yes | `position_source` | 0 ADS-B, 1 ASTERIX, 2 MLAT, 3 FLARM. |
| 17 | category | integer | enum | yes | `category` | Only with `extended=1`. 0 no info, 1 no ADS-B category info, 2 light, 3 small, 4 large, 5 high-vortex large, 6 heavy, 7 high performance, 8 rotorcraft, 9–20 gliders, UAVs, surface vehicles and obstacles. |

A row shorter than 17 elements, or with a wrong JSON type in a typed field, is rejected (FDA-030).

### 2.5 Status codes and FDA handling

| Response | Meaning | FDA action | `poll_runs.status` | Exit |
|---|---|---|---|---|
| 200, valid body | Success | Parse, validate, store | `ok` | 0 |
| 200, invalid body | Format changed or error page | Store nothing | `schema_error` | 3 |
| 429 | Daily credits exhausted | No retry (FDA-005) | `rate_limited` | 2 |
| 5xx, timeout, DNS/TLS/connection error | Server or network fault | Retry ×2, backoff 2 s, 4 s (FDA-006) | `upstream_error` | 3 |
| Other 4xx (400, 401, 403, 404) | Request or credential problem | No retry (FDA-007) | `upstream_error` | 3 |

### 2.6 Rate limits

| Item | Value |
|---|---|
| Daily credits, anonymous | 400 |
| Daily credits, registered user | 4,000 |
| Cost of a `/states/all` query over a box ≤ 25 sq deg | 1 credit (FDA box is 0.76 sq deg) |
| Anonymous time resolution | 10 s (state vectors are current only) |
| `X-Rate-Limit-Remaining` response header | Credits left today; stored as `credits_remaining` |
| `X-Rate-Limit-Retry-After-Seconds` header (on 429) | Logged |

FDA usage: 288 credits/day anonymous at 300 s, 1,440/day authenticated at 60 s.

## 3. IF-2: Database schema

PostgreSQL 14 or later. Source of truth: `src/fda/sql/schema.sql`, applied with
`python -m fda.db init` (idempotent, FDA-025).

### 3.1 `poll_runs`: one row per poll attempt (FDA-024)

| Column | Type | Null | Constraint / meaning |
|---|---|---|---|
| `id` | bigserial | no | Primary key |
| `started_at` | timestamptz | no | Host time when the poll began |
| `finished_at` | timestamptz | yes | Null while `running` or if the process died |
| `status` | text | no | `running`, `ok`, `rate_limited`, `upstream_error`, `schema_error` |
| `http_status` | integer | yes | Last HTTP status received |
| `api_time` | timestamptz | yes | OpenSky `time` for `ok` polls |
| `bbox` | text | no | `lamin,lomin,lamax,lomax` used |
| `authenticated` | boolean | no | Whether OAuth2 was used |
| `n_states` | integer ≥ 0 | yes | Rows in the response |
| `n_inserted` | integer ≥ 0 | yes | Rows stored |
| `n_rejected` | integer ≥ 0 | yes | Rows rejected (FDA-030) |
| `n_flagged` | integer ≥ 0 | yes | Stored rows with at least one flag |
| `credits_remaining` | integer | yes | From `X-Rate-Limit-Remaining` |
| `duration_ms` | integer ≥ 0 | yes | Wall-clock duration |
| `error` | text | yes | Error message for failed polls |

Indexes: `started_at`; partial index on `started_at` where `status = 'ok'`.

### 3.2 `state_vectors`: one row per accepted record

| Column | Type | Null | Constraint / meaning |
|---|---|---|---|
| `id` | bigserial | no | Primary key |
| `poll_id` | bigint | no | FK → `poll_runs.id`, `ON DELETE CASCADE` (retention, FDA-026) |
| `api_time` | timestamptz | no | OpenSky response time |
| `icao24` | char(6) | no | `^[0-9a-f]{6}$` |
| `callsign` | varchar(8) | yes | |
| `origin_country` | text | yes | |
| `time_position` | timestamptz | yes | |
| `last_contact` | timestamptz | no | |
| `longitude` | double precision | yes | −180 to 180 |
| `latitude` | double precision | yes | −90 to 90 |
| `baro_altitude_m` | real | yes | metres |
| `geo_altitude_m` | real | yes | metres |
| `on_ground` | boolean | no | |
| `velocity_mps` | real | yes | m/s |
| `true_track_deg` | real | yes | degrees |
| `vertical_rate_mps` | real | yes | m/s |
| `squawk` | varchar(4) | yes | |
| `spi` | boolean | yes | |
| `position_source` | smallint | yes | 0–3 |
| `category` | smallint | yes | 0–20 |
| `flight_phase` | text | no | Section 3.3 |
| `altitude_band` | text | no | Section 3.3 |
| `dq_flags` | text[] | no | Subset of the flags in section 3.3; `{}` when clean |

Unique key `(icao24, api_time)` (FDA-022); inserts use `ON CONFLICT DO NOTHING`.
Indexes: `api_time`, `poll_id`.

### 3.3 Enumerations and derivation rules

**Phase of flight (FDA-040)**, evaluated in order:

| Phase | Rule |
|---|---|
| GROUND | `on_ground` is true |
| UNKNOWN | barometric altitude is null |
| CLIMB | vertical rate ≥ +2.54 m/s (+500 ft/min) |
| DESCENT | vertical rate ≤ −2.54 m/s |
| CRUISE | altitude ≥ 6,096 m (FL200) |
| LEVEL | anything else |

**Altitude band (FDA-041)**, from barometric altitude in feet (m × 3.28084):
`SURFACE` (on ground), `BELOW_3000FT`, `3000_9999FT`, `10000_17999FT`, `18000_28999FT`,
`FL290_PLUS`, `UNKNOWN` (airborne, altitude null).

**Data-quality flags (FDA-031 to FDA-036):**

| Flag | Condition |
|---|---|
| `MISSING_POSITION` | latitude or longitude null |
| `OUTSIDE_BBOX` | position outside the configured box |
| `STALE_POSITION` | `time` − `time_position` > 60 s |
| `IMPLAUSIBLE_ALTITUDE` | barometric altitude < −300 m or > 18,300 m |
| `IMPLAUSIBLE_SPEED` | velocity < 0 or > 350 m/s |
| `IMPOSSIBLE_JUMP` | implied speed from previous fix > 400 m/s (window 30 min) |

## 4. IF-3: Process interface

### 4.1 Environment (`/etc/fda/fda.env`, mode 600)

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `DATABASE_URL` | yes | – | libpq connection URI |
| `OPENSKY_CLIENT_ID`, `OPENSKY_CLIENT_SECRET` | no | unset | Enable OAuth2 (section 2.3) |
| `FDA_POLL_INTERVAL_S` | no | 300 | Nominal interval; must match the timer |
| `FDA_RETENTION_DAYS` | no | 30 | FDA-026 |
| `FDA_BBOX` | no | ACY box | `lamin,lomin,lamax,lomax` |
| `FDA_STALE_POSITION_S` | no | 60 | FDA-033 threshold |
| `FDA_LOG_LEVEL` | no | INFO | Python logging level |

### 4.2 Exit codes of `python -m fda.ingest` (FDA-053)

| Code | Meaning |
|---|---|
| 0 | Poll succeeded, or was skipped (lock held / rate guard) |
| 1 | Configuration error |
| 2 | Rate limited (HTTP 429) |
| 3 | Upstream error (network, HTTP error, schema error) |
| 4 | Database error |

`python -m fda.health` exits 0 healthy, 1 stale (no `ok` poll within `--max-age-min`),
2 database unreachable.

### 4.3 Log line format (FDA-052)

One line per poll on standard output, captured by journald:

```
<ISO-8601 time> <LEVEL> fda.ingest poll status=<status> states=<n> inserted=<n> rejected=<n> flagged=<n> purged_polls=<n> credits_remaining=<n> duration_ms=<n>
```

Skipped polls log `poll status=skipped reason=<locked|rate_guard>`. Failed polls log
`poll status=<status>` at ERROR level with `http_status` and `error`.
`scripts/inspect_logs.sh` parses these fields; changing them is an interface change.
