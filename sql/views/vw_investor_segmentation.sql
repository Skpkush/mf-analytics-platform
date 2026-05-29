-- ============================================================
-- vw_investor_segmentation
-- Investor-level aggregated analytics.
-- One row per investor, summarising all their transactions.
--
-- Used by:
--   Power BI Page 3 — Investor Analytics (SIP trends, segmentation)
--   Streamlit Risk Profiler — investor lookup and recommendation
--
-- All investors from Dim_Investor are included even if they have
-- no transactions (zero values via COALESCE).
-- ============================================================

CREATE OR REPLACE VIEW dbo.vw_investor_segmentation AS
WITH txn_summary AS (
    -- Aggregate all transaction types per investor-fund in one pass
    SELECT
        investor_key,
        fund_key,
        SUM(CASE WHEN transaction_type IN ('SIP', 'Lumpsum')
                 THEN amount ELSE 0 END)     AS invested,
        SUM(CASE WHEN transaction_type = 'Redemption'
                 THEN amount ELSE 0 END)     AS redeemed,
        SUM(CASE WHEN transaction_type = 'SIP'
                 THEN 1 ELSE 0 END)          AS sip_count,
        SUM(CASE WHEN transaction_type = 'Lumpsum'
                 THEN 1 ELSE 0 END)          AS lumpsum_count,
        SUM(CASE WHEN transaction_type = 'Redemption'
                 THEN 1 ELSE 0 END)          AS redemption_count,
        COUNT(*)                              AS total_txn_count
    FROM dbo.Fact_Transactions
    GROUP BY investor_key, fund_key
),
investor_summary AS (
    -- Roll up from per-fund to per-investor
    SELECT
        investor_key,
        SUM(invested)            AS total_invested,
        SUM(redeemed)            AS total_redeemed,
        COUNT(DISTINCT fund_key) AS active_funds,
        SUM(sip_count)           AS sip_count,
        SUM(lumpsum_count)       AS lumpsum_count,
        SUM(redemption_count)    AS redemption_count,
        SUM(total_txn_count)     AS total_txn_count
    FROM txn_summary
    GROUP BY investor_key
)
SELECT
    di.investor_id,
    di.age_group,
    di.city,
    di.state,
    di.risk_profile,
    di.investor_segment,
    di.kyc_status,

    -- Investment totals
    COALESCE(s.total_invested,   0)                               AS total_invested,
    COALESCE(s.total_redeemed,   0)                               AS total_redeemed,
    COALESCE(s.total_invested, 0) - COALESCE(s.total_redeemed, 0) AS net_invested,

    -- Portfolio activity
    COALESCE(s.active_funds,     0)                               AS active_funds,
    COALESCE(s.sip_count,        0)                               AS sip_count,
    COALESCE(s.lumpsum_count,    0)                               AS lumpsum_count,
    COALESCE(s.redemption_count, 0)                               AS redemption_count,
    COALESCE(s.total_txn_count,  0)                               AS total_txn_count
FROM dbo.Dim_Investor di
LEFT JOIN investor_summary s ON s.investor_key = di.investor_key;

COMMENT ON VIEW dbo.vw_investor_segmentation IS
    'Per-investor transaction summary: invested, redeemed, net, fund count, SIP/lumpsum breakdown. All 500 investors included (zero values for inactive ones).';
