-- 04_rule_performance.sql
-- Precision = share of alerts that are real fraud (alert quality / analyst workload)
-- Recall    = share of all fraud that the rule catches (coverage)
WITH totals AS (
    SELECT SUM(isfraud) AS all_fraud FROM txn_flags
),
scored AS (
    SELECT *,
           r1_account_drain + r2_large_transfer + r3_dest_mismatch + r4_night_activity AS rules_hit
    FROM txn_flags
),
rules AS (
    SELECT 'Existing control (>200k rule)' AS rule, SUM(isflaggedfraud) AS alerts, SUM(isflaggedfraud * isfraud) AS tp FROM scored
    UNION ALL SELECT 'R1 Account drain',      SUM(r1_account_drain),  SUM(r1_account_drain  * isfraud) FROM scored
    UNION ALL SELECT 'R2 Large transfer',     SUM(r2_large_transfer), SUM(r2_large_transfer * isfraud) FROM scored
    UNION ALL SELECT 'R3 Destination mismatch', SUM(r3_dest_mismatch), SUM(r3_dest_mismatch * isfraud) FROM scored
    UNION ALL SELECT 'R4 Night activity',     SUM(r4_night_activity), SUM(r4_night_activity * isfraud) FROM scored
    UNION ALL SELECT 'Combined (2+ rules hit)',
                     SUM(CASE WHEN rules_hit >= 2 THEN 1 ELSE 0 END),
                     SUM(CASE WHEN rules_hit >= 2 THEN isfraud ELSE 0 END) FROM scored
)
SELECT
    rule,
    alerts,
    tp                                            AS true_positives,
    alerts - tp                                   AS false_positives,
    ROUND(100.0 * tp / NULLIF(alerts, 0), 2)      AS precision_pct,
    ROUND(100.0 * tp / NULLIF(all_fraud, 0), 2)   AS recall_pct
FROM rules, totals;
