-- Observations by altitude band and phase of flight (REQ-032).
SELECT altitude_band,
       flight_phase,
       count(*)                                            AS observations,
       count(DISTINCT icao24)                              AS distinct_aircraft,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1)  AS pct_of_obs
FROM state_vectors
WHERE api_time >= %(since)s AND api_time < %(until)s
GROUP BY altitude_band, flight_phase
ORDER BY array_position(
             ARRAY['SURFACE', 'BELOW_3000FT', '3000_9999FT', '10000_17999FT',
                   '18000_28999FT', 'FL290_PLUS', 'UNKNOWN']::text[],
             altitude_band),
         observations DESC;
