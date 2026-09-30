-- 05_fraud_by_hour.sql
-- Fraud rate by hour of day for high-risk transaction types.
SELECT
    hour_of_day,
    COUNT(*)                                      AS transactions,
    SUM(isfraud)                                  AS fraud_transactions,
    ROUND(100.0 * SUM(isfraud) / COUNT(*), 3)     AS fraud_rate_pct
FROM txn_flags
WHERE type IN ('TRANSFER', 'CASH_OUT')
GROUP BY hour_of_day
ORDER BY hour_of_day;
