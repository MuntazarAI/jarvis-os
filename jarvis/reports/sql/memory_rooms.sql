SELECT
    room,
    tier,
    COUNT(*) AS count,
    MAX(created_at) AS last_at
FROM memories
WHERE archived = 0 AND expired = 0
GROUP BY room, tier
ORDER BY count DESC, room ASC, tier ASC
LIMIT :limit;
