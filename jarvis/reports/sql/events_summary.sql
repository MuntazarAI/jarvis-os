SELECT
    type,
    COUNT(*) AS count,
    MIN(timestamp) AS first_at,
    MAX(timestamp) AS last_at
FROM events
GROUP BY type
ORDER BY count DESC, type ASC
LIMIT :limit;
