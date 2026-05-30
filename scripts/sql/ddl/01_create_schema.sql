-- ============================================================
-- 01_create_schema.sql
-- Create the dbo schema and enable required extensions.
--
-- Run order: first. All other DDL files depend on this.
-- ============================================================

CREATE SCHEMA IF NOT EXISTS dbo;

-- Required for gen_random_uuid() if used in future DML scripts.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

COMMENT ON SCHEMA dbo IS
    'Mutual Fund Analytics Platform — star schema for Power BI, Streamlit, and metrics pipeline.';
