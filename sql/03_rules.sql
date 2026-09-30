-- 03_rules.sql
-- Detection rules based on common AML / fraud typologies.
-- Each rule is a 0/1 flag so rules can be measured individually and combined.
CREATE OR REPLACE TABLE txn_flags AS
SELECT
    t.*,
    step % 24                                             AS hour_of_day,
    CAST(FLOOR((step - 1) / 24) + 1 AS INTEGER)           AS day,

    -- R1 Account drain: sender's balance fully emptied in one high-risk transaction
    CASE WHEN type IN ('TRANSFER', 'CASH_OUT')
              AND oldbalanceorg > 0
              AND amount >= oldbalanceorg
         THEN 1 ELSE 0 END                                AS r1_account_drain,

    -- R2 Large transfer: single transfer above the reporting-style threshold
    CASE WHEN type = 'TRANSFER' AND amount > 200000
         THEN 1 ELSE 0 END                                AS r2_large_transfer,

    -- R3 Destination mismatch: money sent, but receiver balance shows no movement
    CASE WHEN type IN ('TRANSFER', 'CASH_OUT')
              AND amount > 0
              AND oldbalancedest = 0 AND newbalancedest = 0
         THEN 1 ELSE 0 END                                AS r3_dest_mismatch,

    -- R4 Night activity: high-risk transaction types between midnight and 6 AM
    CASE WHEN type IN ('TRANSFER', 'CASH_OUT')
              AND step % 24 BETWEEN 0 AND 5
         THEN 1 ELSE 0 END                                AS r4_night_activity
FROM transactions t;
