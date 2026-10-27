-- Flight Data Analyzer schema (ICD section 3). Idempotent: safe to re-run.
-- Unqualified names so tests can apply it inside a throwaway schema.

CREATE TABLE IF NOT EXISTS poll_runs (
    id                bigserial PRIMARY KEY,
    started_at        timestamptz NOT NULL DEFAULT now(),
    finished_at       timestamptz,
    status            text NOT NULL
                      CHECK (status IN ('running', 'ok', 'rate_limited',
                                        'upstream_error', 'schema_error')),
    http_status       integer,
    api_time          timestamptz,
    bbox              text NOT NULL,
    authenticated     boolean NOT NULL,
    n_states          integer CHECK (n_states >= 0),
    n_inserted        integer CHECK (n_inserted >= 0),
    n_rejected        integer CHECK (n_rejected >= 0),
    n_flagged         integer CHECK (n_flagged >= 0),
    credits_remaining integer,
    duration_ms       integer CHECK (duration_ms >= 0),
    error             text
);

CREATE INDEX IF NOT EXISTS poll_runs_started_at_idx ON poll_runs (started_at);
CREATE INDEX IF NOT EXISTS poll_runs_ok_idx ON poll_runs (started_at) WHERE status = 'ok';

CREATE TABLE IF NOT EXISTS state_vectors (
    id                bigserial PRIMARY KEY,
    poll_id           bigint NOT NULL REFERENCES poll_runs (id) ON DELETE CASCADE,
    api_time          timestamptz NOT NULL,
    icao24            char(6) NOT NULL CHECK (icao24 ~ '^[0-9a-f]{6}$'),
    callsign          varchar(8),
    origin_country    text,
    time_position     timestamptz,
    last_contact      timestamptz NOT NULL,
    longitude         double precision CHECK (longitude BETWEEN -180 AND 180),
    latitude          double precision CHECK (latitude BETWEEN -90 AND 90),
    baro_altitude_m   real,
    geo_altitude_m    real,
    on_ground         boolean NOT NULL,
    velocity_mps      real,
    true_track_deg    real,
    vertical_rate_mps real,
    squawk            varchar(4),
    spi               boolean,
    position_source   smallint CHECK (position_source BETWEEN 0 AND 3),
    category          smallint CHECK (category BETWEEN 0 AND 20),
    flight_phase      text NOT NULL
                      CHECK (flight_phase IN ('GROUND', 'CLIMB', 'DESCENT', 'CRUISE',
                                              'LEVEL', 'UNKNOWN')),
    altitude_band     text NOT NULL
                      CHECK (altitude_band IN ('SURFACE', 'BELOW_3000FT', '3000_9999FT',
                                               '10000_17999FT', '18000_28999FT',
                                               'FL290_PLUS', 'UNKNOWN')),
    dq_flags          text[] NOT NULL DEFAULT '{}'
                      CHECK (dq_flags <@ ARRAY['MISSING_POSITION', 'OUTSIDE_BBOX',
                                               'STALE_POSITION', 'IMPLAUSIBLE_ALTITUDE',
                                               'IMPLAUSIBLE_SPEED', 'IMPOSSIBLE_JUMP']::text[]),
    CONSTRAINT state_vectors_icao24_api_time_key UNIQUE (icao24, api_time)
);

CREATE INDEX IF NOT EXISTS state_vectors_api_time_idx ON state_vectors (api_time);
CREATE INDEX IF NOT EXISTS state_vectors_poll_id_idx ON state_vectors (poll_id);
