-- Gaps between consecutive successful polls longer than twice the nominal interval
-- (REQ-034). Causes include API outages, rate limiting, host downtime and WSL shutdown.
WITH ok AS (
    SELECT started_at,
           lag(started_at) OVER (ORDER BY started_at) AS prev_ok
    FROM poll_runs
    WHERE status = 'ok' AND started_at >= %(since)s AND started_at < %(until)s
)
SELECT prev_ok AT TIME ZONE %(tz)s                                   AS gap_start_local,
       started_at AT TIME ZONE %(tz)s                                AS gap_end_local,
       round((extract(epoch FROM started_at - prev_ok) / 60.0)::numeric, 1) AS gap_minutes
FROM ok
WHERE prev_ok IS NOT NULL
  AND started_at - prev_ok > make_interval(secs => 2 * %(interval_s)s)
ORDER BY gap_minutes DESC
LIMIT 25;
