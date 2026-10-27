-- Distinct aircraft and observations per calendar hour, local time (REQ-030).
SELECT date_trunc('hour', api_time AT TIME ZONE %(tz)s)  AS hour_start_local,
       count(DISTINCT icao24)                           AS distinct_aircraft,
       count(*)                                         AS observations,
       count(*) FILTER (WHERE on_ground)                AS on_ground_obs
FROM state_vectors
WHERE api_time >= %(since)s AND api_time < %(until)s
GROUP BY 1
ORDER BY 1;
