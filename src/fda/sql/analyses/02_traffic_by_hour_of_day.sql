-- Aircraft in view per successful poll, averaged by local hour of day (REQ-030).
-- Normalizing per poll keeps hours with missed polls comparable to the rest.
WITH per_poll AS (
    SELECT p.id, p.started_at, count(s.id) AS aircraft
    FROM poll_runs p
    LEFT JOIN state_vectors s ON s.poll_id = p.id
    WHERE p.status = 'ok' AND p.started_at >= %(since)s AND p.started_at < %(until)s
    GROUP BY p.id, p.started_at
)
SELECT extract(hour FROM started_at AT TIME ZONE %(tz)s)::int AS hour_local,
       count(*)                                              AS polls,
       round(avg(aircraft), 1)                               AS avg_aircraft_in_view,
       max(aircraft)                                         AS peak_aircraft_in_view
FROM per_poll
GROUP BY 1
ORDER BY 1;
