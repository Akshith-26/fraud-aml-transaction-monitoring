-- 01_profile.sql
-- Where does fraud happen? Fraud volume and value by transaction type.
SELECT
    type,
    COUNT(*)                                             AS transactions,
    SUM(isfraud)                                         AS fraud_transactions,
    ROUND(100.0 * SUM(isfraud) / COUNT(*), 4)            AS fraud_rate_pct,
    ROUND(SUM(amount), 0)                                AS total_amount,
    ROUND(SUM(CASE WHEN isfraud = 1 THEN amount ELSE 0 END), 0) AS fraud_amount
FROM transactions
GROUP BY type
ORDER BY fraud_transactions DESC, transactions DESC;
