-- 02_existing_control.sql
-- How well does the existing control (isFlaggedFraud: transfers > 200,000) work?
SELECT
    SUM(isflaggedfraud)                                   AS alerts,
    SUM(isflaggedfraud * isfraud)                         AS true_positives,
    SUM(isfraud)                                          AS total_fraud,
    ROUND(100.0 * SUM(isflaggedfraud * isfraud) / NULLIF(SUM(isfraud), 0), 2) AS recall_pct
FROM transactions;
