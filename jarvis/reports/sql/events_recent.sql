SELECT
    seq,
    type,
    correlation_id,
    timestamp,
    substr(payload, 1, 200) AS payload
FROM events
ORDER BY seq DESC
LIMIT :limit;
