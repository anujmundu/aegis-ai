-- =============================================================================
-- AegisAI: Production Relational Schema & Episodic Incident Memory
-- Database: PostgreSQL 15+ (Compatible with asyncpg and SQLAlchemy)
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- -----------------------------------------------------------------------------
-- 1. Microservice Catalog
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS services (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    tier VARCHAR(32) NOT NULL DEFAULT 'application', -- infrastructure | application | database | business
    criticality VARCHAR(16) NOT NULL DEFAULT 'HIGH', -- CRITICAL | HIGH | MEDIUM | LOW
    owner_team VARCHAR(64) NOT NULL DEFAULT 'platform-sre',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- 2. Multi-Tier Telemetry History (Time-Series Table)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS telemetry_records (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    service_id VARCHAR(64) NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    trace_id VARCHAR(64) NOT NULL,
    
    -- Infrastructure Tier
    cpu_percent NUMERIC(5,2) NOT NULL,
    memory_percent NUMERIC(5,2) NOT NULL,
    disk_io_mbps NUMERIC(8,2) NOT NULL,
    network_mbps NUMERIC(8,2) NOT NULL,
    
    -- Application Tier
    latency_p50_ms NUMERIC(8,2) NOT NULL,
    latency_p95_ms NUMERIC(8,2) NOT NULL,
    latency_p99_ms NUMERIC(8,2) NOT NULL,
    requests_per_sec NUMERIC(8,2) NOT NULL,
    http_2xx_count INT NOT NULL DEFAULT 0,
    http_4xx_count INT NOT NULL DEFAULT 0,
    http_5xx_count INT NOT NULL DEFAULT 0,
    error_rate NUMERIC(5,4) NOT NULL DEFAULT 0.0,
    
    -- Database Tier
    db_query_latency_ms NUMERIC(8,2) NOT NULL,
    db_pool_utilization NUMERIC(5,2) NOT NULL,
    db_row_locks INT NOT NULL DEFAULT 0,
    
    -- Business Tier
    order_volume INT NOT NULL DEFAULT 0,
    revenue_usd NUMERIC(10,2) NOT NULL DEFAULT 0.0,
    checkout_success_rate NUMERIC(5,2) NOT NULL DEFAULT 100.0,
    
    -- Ground Truth & Model Inference Flags
    is_anomalous BOOLEAN NOT NULL DEFAULT FALSE,
    anomaly_score NUMERIC(5,4),
    ground_truth_label VARCHAR(64) NOT NULL DEFAULT 'NOMINAL'
);

CREATE INDEX IF NOT EXISTS idx_telemetry_time_service ON telemetry_records (timestamp DESC, service_id);
CREATE INDEX IF NOT EXISTS idx_telemetry_anomalous ON telemetry_records (is_anomalous, timestamp DESC);

-- -----------------------------------------------------------------------------
-- 3. Incident Lifecycle & Investigation Memory
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS incidents (
    id VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,
    title VARCHAR(256) NOT NULL,
    severity VARCHAR(16) NOT NULL, -- CRITICAL | HIGH | MEDIUM | LOW
    status VARCHAR(32) NOT NULL DEFAULT 'DETECTED', -- DETECTED | INVESTIGATING | ROOT_CAUSE_IDENTIFIED | REMEDIATION_PROPOSED | RESOLVED
    service_id VARCHAR(64) NOT NULL REFERENCES services(id),
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    root_cause_hypothesis TEXT,
    confidence_score NUMERIC(4,3),
    postmortem_markdown TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_incidents_status_sev ON incidents (status, severity, detected_at DESC);

-- -----------------------------------------------------------------------------
-- 4. Incident Correlated Signals (Evidence Graph Nodes)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS incident_signals (
    id BIGSERIAL PRIMARY KEY,
    incident_id VARCHAR(36) NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    signal_name VARCHAR(128) NOT NULL,
    observed_value NUMERIC(10,2) NOT NULL,
    baseline_value NUMERIC(10,2) NOT NULL,
    deviation_sigma NUMERIC(6,2) NOT NULL,
    is_primary_driver BOOLEAN NOT NULL DEFAULT FALSE,
    detected_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_signals_incident ON incident_signals (incident_id);

-- -----------------------------------------------------------------------------
-- 5. Grounded Citations & RAG Evidence Linkage
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS incident_evidence (
    id BIGSERIAL PRIMARY KEY,
    incident_id VARCHAR(36) NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    evidence_type VARCHAR(32) NOT NULL, -- TELEMETRY | RUNBOOK | HISTORICAL_INCIDENT | ARCHITECTURE_DOC
    source_uri VARCHAR(256) NOT NULL,
    chunk_id VARCHAR(64),
    citation_text TEXT NOT NULL,
    grounding_score NUMERIC(4,3) NOT NULL DEFAULT 1.0,
    is_contradicting BOOLEAN NOT NULL DEFAULT FALSE,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evidence_incident ON incident_evidence (incident_id);

-- -----------------------------------------------------------------------------
-- 6. Remediation Actions & Human Approval Audit Trail
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS remediation_audit (
    id VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,
    incident_id VARCHAR(36) NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    action_type VARCHAR(64) NOT NULL, -- INCREASE_POOL | RESTART_SERVICE | SCALE_DEPLOYMENT | CLEAR_CACHE
    target_resource VARCHAR(128) NOT NULL,
    risk_level VARCHAR(16) NOT NULL DEFAULT 'LOW', -- LOW | MEDIUM | HIGH
    status VARCHAR(32) NOT NULL DEFAULT 'PROPOSED', -- PROPOSED | APPROVED | EXECUTED | REJECTED | FAILED
    requires_human_approval BOOLEAN NOT NULL DEFAULT TRUE,
    proposed_by VARCHAR(64) NOT NULL DEFAULT 'action-agent',
    approved_by VARCHAR(128),
    approval_token VARCHAR(256),
    execution_result TEXT,
    post_remediation_latency_diff_pct NUMERIC(6,2),
    proposed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    executed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_remediation_incident ON remediation_audit (incident_id);

-- Seed Essential Core Services
INSERT INTO services (id, name, tier, criticality, owner_team) VALUES
    ('checkout-service', 'E-Commerce Checkout & Payment Microservice', 'application', 'CRITICAL', 'checkout-eng'),
    ('order-processing', 'Order Ingestion & State Machine Service', 'application', 'CRITICAL', 'order-eng'),
    ('aurora-postgres-primary', 'Primary Transactional PostgreSQL Cluster', 'database', 'CRITICAL', 'database-sre'),
    ('redis-session-store', 'Distributed Session & Cart Cache Cluster', 'database', 'HIGH', 'platform-sre'),
    ('kubernetes-cluster-core', 'Production EKS/GKE Node Pool Infrastructure', 'infrastructure', 'CRITICAL', 'infra-sre')
ON CONFLICT (id) DO NOTHING;
