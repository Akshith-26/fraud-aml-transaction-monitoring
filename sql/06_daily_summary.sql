-- 06_daily_summary.sql
-- Daily monitoring summary (feeds the dashboard trend view).
SELECT
    day,
    type,
    COUNT(*)                   AS transactions,
    SUM(isfraud)               AS fraud_transactions,
    ROUND(SUM(amount), 0)      AS total_amount,
    ROUND(SUM(CASE WHEN isfraud = 1 THEN amount ELSE 0 END), 0) AS fraud_amount
FROM txn_flags
GROUP BY day, type
ORDER BY day, type;
