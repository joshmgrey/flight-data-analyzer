-- Data-quality flag counts as a share of stored observations (REQ-033).
-- A record can carry several flags, so flag rows do not sum to 100 percent.
-- (No literal percent signs in these files: psycopg treats them as placeholders.)
WITH scope AS (
    SELECT dq_flags
    FROM state_vectors
    WHERE api_time >= %(since)s AND api_time < %(until)s
),
counts AS (
    SELECT f.flag, count(*) AS observations
    FROM scope CROSS JOIN LATERAL unnest(scope.dq_flags) AS f(flag)
    GROUP BY f.flag
    UNION ALL
    SELECT 'CLEAN (no flags)', count(*)
    FROM scope
    WHERE cardinality(dq_flags) = 0
)
SELECT flag,
       observations,
       round(100.0 * observations / nullif((SELECT count(*) FROM scope), 0), 2) AS pct_of_obs
FROM counts
ORDER BY observations DESC, flag;
