-- =============================================================================
-- AegisAI: Executive Analytics Star Schema & Relational BI Views
-- Compatible with: PostgreSQL 15+, Power BI DirectQuery, Tableau Live Connections
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Dimension Tables
-- -----------------------------------------------------------------------------

-- Dimension: Services
CREATE TABLE IF NOT EXISTS dim_service (
    service_id VARCHAR(64) PRIMARY KEY,
    service_name VARCHAR(128) NOT NULL,
    tier VARCHAR(32) NOT NULL,          -- infrastructure | application | database
    criticality VARCHAR(16) NOT NULL,   -- CRITICAL | HIGH | MEDIUM | LOW
    owner_team VARCHAR(64) NOT NULL
);

-- Dimension: Severity
CREATE TABLE IF NOT EXISTS dim_severity (
    severity_code VARCHAR(16) PRIMARY KEY, -- CRITICAL | HIGH | MEDIUM | LOW
    severity_name VARCHAR(64) NOT NULL,
    hourly_cost_rate_usd NUMERIC(10,2) NOT NULL,
    target_sla_minutes INT NOT NULL
);

-- Dimension: Incident Archetype
CREATE TABLE IF NOT EXISTS dim_archetype (
    archetype_id VARCHAR(64) PRIMARY KEY,
    archetype_name VARCHAR(128) NOT NULL,
    primary_tier VARCHAR(32) NOT NULL,
    description TEXT
);

-- Dimension: Date / Time
CREATE TABLE IF NOT EXISTS dim_date (
    date_key INT PRIMARY KEY,           -- Format: YYYYMMDD
    full_date DATE NOT NULL,
    year INT NOT NULL,
    quarter INT NOT NULL,
    month INT NOT NULL,
    month_name VARCHAR(16) NOT NULL,
    day_of_month INT NOT NULL,
    day_name VARCHAR(16) NOT NULL,
    is_weekend BOOLEAN NOT NULL
);

-- -----------------------------------------------------------------------------
-- 2. Fact Tables
-- -----------------------------------------------------------------------------

-- Fact: Incident Financial & Reliability Analytics
CREATE TABLE IF NOT EXISTS fact_incident_financials (
    incident_id VARCHAR(64) PRIMARY KEY,
    date_key INT NOT NULL REFERENCES dim_date(date_key),
    detected_timestamp TIMESTAMPTZ NOT NULL,
    resolved_timestamp TIMESTAMPTZ,
    service_id VARCHAR(64) NOT NULL REFERENCES dim_service(service_id),
    severity_code VARCHAR(16) NOT NULL REFERENCES dim_severity(severity_code),
    archetype_id VARCHAR(64) NOT NULL REFERENCES dim_archetype(archetype_id),
    
    -- MTTR Duration Metrics (in Minutes)
    baseline_mttr_minutes NUMERIC(8,2) NOT NULL DEFAULT 90.0,
    actual_mttr_minutes NUMERIC(8,2) NOT NULL,
    mttr_reduction_minutes NUMERIC(8,2) NOT NULL,
    
    -- Financial Impact Metrics (USD)
    hourly_downtime_rate NUMERIC(10,2) NOT NULL,
    baseline_downtime_cost NUMERIC(12,2) NOT NULL,
    actual_downtime_cost NUMERIC(12,2) NOT NULL,
    downtime_savings_gross NUMERIC(12,2) NOT NULL,
    
    -- SRE Labor Reclaimed
    engineering_hours_saved NUMERIC(8,2) NOT NULL,
    engineering_cost_saved NUMERIC(10,2) NOT NULL,
    
    -- Net Value Delivered
    total_gross_value_delivered NUMERIC(12,2) NOT NULL,
    realized_net_savings NUMERIC(12,2) NOT NULL, -- 25% conservative realization
    
    -- Quality & Flag Attributes
    is_false_positive BOOLEAN NOT NULL DEFAULT FALSE,
    resolution_status VARCHAR(32) NOT NULL DEFAULT 'RESOLVED',
    grounding_score NUMERIC(4,3) NOT NULL DEFAULT 1.0
);

CREATE INDEX IF NOT EXISTS idx_fact_incident_date ON fact_incident_financials (date_key);
CREATE INDEX IF NOT EXISTS idx_fact_incident_service ON fact_incident_financials (service_id);
CREATE INDEX IF NOT EXISTS idx_fact_incident_severity ON fact_incident_financials (severity_code);

-- -----------------------------------------------------------------------------
-- 3. Analytical Views for Power BI & Tableau
-- -----------------------------------------------------------------------------

-- View 1: Executive KPI Overview Banner
CREATE OR REPLACE VIEW view_executive_summary_kpi AS
SELECT 
    COUNT(incident_id) AS total_incidents,
    SUM(CASE WHEN resolution_status = 'RESOLVED' AND NOT is_false_positive THEN 1 ELSE 0 END) AS resolved_incidents,
    SUM(CASE WHEN is_false_positive THEN 1 ELSE 0 END) AS false_positives,
    ROUND(
        (SUM(CASE WHEN is_false_positive THEN 1.0 ELSE 0.0 END) / COUNT(incident_id) * 100.0), 2
    ) AS false_positive_rate_pct,
    ROUND(AVG(CASE WHEN NOT is_false_positive THEN baseline_mttr_minutes END), 1) AS baseline_avg_mttr_mins,
    ROUND(AVG(CASE WHEN NOT is_false_positive THEN actual_mttr_minutes END), 1) AS aegis_avg_mttr_mins,
    ROUND(
        (AVG(CASE WHEN NOT is_false_positive THEN baseline_mttr_minutes END) - 
         AVG(CASE WHEN NOT is_false_positive THEN actual_mttr_minutes END)) / 
        AVG(CASE WHEN NOT is_false_positive THEN baseline_mttr_minutes END) * 100.0, 1
    ) AS mttr_reduction_pct,
    SUM(downtime_savings_gross) AS total_downtime_savings_gross_usd,
    SUM(engineering_hours_saved) AS total_engineering_hours_saved,
    SUM(engineering_cost_saved) AS total_engineering_cost_saved_usd,
    SUM(total_gross_value_delivered) AS total_gross_value_delivered_usd,
    SUM(realized_net_savings) AS realized_net_savings_usd,
    15000.0 AS annual_platform_cost_usd,
    ROUND(
        ((SUM(realized_net_savings) - 15000.0) / 15000.0 * 100.0), 1
    ) AS net_roi_pct,
    ROUND(
        (15000.0 / (SUM(realized_net_savings) / 365.0)), 1
    ) AS payback_period_days
FROM fact_incident_financials;

-- View 2: Microservice Downtime & Exposure Breakdown
CREATE OR REPLACE VIEW view_service_downtime_exposure AS
SELECT 
    s.service_id,
    s.service_name,
    s.tier,
    s.criticality,
    s.owner_team,
    COUNT(f.incident_id) AS incident_count,
    SUM(CASE WHEN f.severity_code = 'CRITICAL' THEN 1 ELSE 0 END) AS critical_p1_count,
    ROUND(AVG(f.actual_mttr_minutes), 1) AS avg_mttr_minutes,
    SUM(f.actual_downtime_cost) AS total_downtime_cost_incurred,
    SUM(f.downtime_savings_gross) AS total_downtime_savings_avoided,
    ROUND(
        GREATEST(99.000, 100.000 - (SUM(f.actual_mttr_minutes) / 525600.0 * 100.0)), 3
    ) AS availability_sla_pct
FROM dim_service s
LEFT JOIN fact_incident_financials f ON s.service_id = f.service_id
GROUP BY s.service_id, s.service_name, s.tier, s.criticality, s.owner_team
ORDER BY total_downtime_savings_avoided DESC;

-- View 3: Monthly Reliability & Financial Value Trend
CREATE OR REPLACE VIEW view_monthly_roi_trend AS
SELECT 
    d.year,
    d.month,
    CONCAT(d.year, '-', LPAD(d.month::TEXT, 2, '0')) AS year_month,
    COUNT(f.incident_id) AS incident_count,
    SUM(CASE WHEN f.severity_code = 'CRITICAL' THEN 1 ELSE 0 END) AS p1_count,
    SUM(CASE WHEN f.severity_code = 'HIGH' THEN 1 ELSE 0 END) AS p2_count,
    SUM(CASE WHEN f.severity_code = 'MEDIUM' THEN 1 ELSE 0 END) AS p3_count,
    ROUND(SUM(f.actual_mttr_minutes) / 60.0, 1) AS aegis_downtime_hours,
    ROUND(SUM(f.mttr_reduction_minutes) / 60.0, 1) AS downtime_hours_avoided,
    SUM(f.downtime_savings_gross) AS downtime_savings_usd,
    SUM(f.engineering_cost_saved) AS engineering_cost_saved_usd,
    SUM(f.total_gross_value_delivered) AS gross_value_delivered_usd,
    SUM(f.realized_net_savings) AS realized_net_savings_usd
FROM dim_date d
JOIN fact_incident_financials f ON d.date_key = f.date_key
GROUP BY d.year, d.month
ORDER BY d.year, d.month;

-- View 4: Archetype Pareto 80/20 Analysis
CREATE OR REPLACE VIEW view_incident_archetype_pareto AS
SELECT 
    a.archetype_id,
    a.archetype_name,
    a.primary_tier,
    COUNT(f.incident_id) AS incident_count,
    ROUND((COUNT(f.incident_id)::NUMERIC / (SELECT COUNT(*) FROM fact_incident_financials) * 100.0), 1) AS incident_percentage,
    SUM(f.actual_downtime_cost) AS total_downtime_cost_usd,
    SUM(f.downtime_savings_gross) AS total_savings_usd,
    ROUND(AVG(f.mttr_reduction_minutes), 1) AS avg_mttr_minutes_saved
FROM dim_archetype a
JOIN fact_incident_financials f ON a.archetype_id = f.archetype_id
GROUP BY a.archetype_id, a.archetype_name, a.primary_tier
ORDER BY total_savings_usd DESC;
