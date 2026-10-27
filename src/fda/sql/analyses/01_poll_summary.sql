-- Poll outcomes: availability of the OpenSky feed and of this collector (REQ-034).
SELECT status,
       count(*)                                               AS polls,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1)     AS pct_of_polls,
       count(*) FILTER (WHERE n_states = 0)                   AS polls_with_zero_aircraft,
       coalesce(sum(n_rejected), 0)                           AS rejected_rows,
       min(credits_remaining)                                 AS min_credits_remaining,
       round(avg(duration_ms))                                AS avg_duration_ms
FROM poll_runs
WHERE started_at >= %(since)s AND started_at < %(until)s
GROUP BY status
ORDER BY polls DESC;
