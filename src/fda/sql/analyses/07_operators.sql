-- Traffic mix by callsign pattern. Three letters plus a digit is an ICAO airline
-- designator (e.g. AAL, JBU); "N" plus a digit is a U.S. registration, usually GA.
SELECT CASE
           WHEN callsign IS NULL                THEN 'No callsign'
           WHEN callsign ~ '^[A-Z]{3}[0-9]'     THEN left(callsign, 3)
           WHEN callsign ~ '^N[0-9]'            THEN 'N-number (GA/private)'
           ELSE 'Other'
       END                     AS operator,
       count(DISTINCT icao24)  AS distinct_aircraft,
       count(*)                AS observations
FROM state_vectors
WHERE api_time >= %(since)s AND api_time < %(until)s
GROUP BY 1
ORDER BY distinct_aircraft DESC, operator
LIMIT 20;
