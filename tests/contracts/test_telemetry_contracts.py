"""Tests for Pydantic v2 Telemetry Event Contracts & Schemas."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from data.schemas.events import (
    AnomalyArchetype,
    ApplicationMetrics,
    BusinessMetrics,
    DatabaseMetrics,
    IncidentCreate,
    IncidentSeverity,
    InfrastructureMetrics,
    RemediationProposal,
    TelemetrySnapshot,
)


def test_infrastructure_metrics_valid():
    """Verify valid infrastructure metrics instantiation."""
    infra = InfrastructureMetrics(
        cpu_percent=45.5,
        memory_percent=60.2,
        disk_io_mbps=24.5,
        network_egress_mbps=75.0,
        network_ingress_mbps=32.0,
    )
    assert infra.cpu_percent == 45.5
    assert infra.memory_percent == 60.2


def test_infrastructure_metrics_out_of_bounds():
    """Verify out-of-bounds CPU/Memory values raise ValidationError."""
    with pytest.raises(ValidationError):
        InfrastructureMetrics(
            cpu_percent=105.0,  # Invalid: >100%
            memory_percent=50.0,
            disk_io_mbps=10.0,
            network_egress_mbps=10.0,
            network_ingress_mbps=10.0,
        )

    with pytest.raises(ValidationError):
        InfrastructureMetrics(
            cpu_percent=50.0,
            memory_percent=-5.0,  # Invalid: <0%
            disk_io_mbps=10.0,
            network_egress_mbps=10.0,
            network_ingress_mbps=10.0,
        )


def test_application_metrics_error_rate():
    """Verify application error rate computation."""
    app = ApplicationMetrics(
        service_id="checkout-service",
        endpoint="/api/v1/checkout",
        requests_per_sec=100.0,
        latency_p50_ms=25.0,
        latency_p95_ms=65.0,
        latency_p99_ms=110.0,
        http_2xx_count=950,
        http_4xx_count=30,
        http_5xx_count=20,
    )
    assert app.error_rate == pytest.approx(0.02, rel=1e-3)


def test_database_metrics_pool_bounds():
    """Verify database metrics pool percentage boundary checks."""
    db = DatabaseMetrics(
        db_instance_id="aurora-postgres-primary",
        active_connections=35,
        connection_pool_utilization=35.5,
        query_latency_mean_ms=8.2,
        slow_queries_per_sec=0.1,
        row_lock_waits=0,
    )
    assert db.connection_pool_utilization == 35.5

    with pytest.raises(ValidationError):
        DatabaseMetrics(
            db_instance_id="aurora-postgres-primary",
            active_connections=35,
            connection_pool_utilization=105.0,  # Invalid: >100%
            query_latency_mean_ms=8.2,
        )


def test_business_metrics_bounds():
    """Verify business KPIs bounds enforcement."""
    biz = BusinessMetrics(
        order_volume=120,
        revenue_usd=5400.0,
        checkout_success_rate=99.2,
        cart_abandonment_rate=18.4,
    )
    assert biz.checkout_success_rate == 99.2

    with pytest.raises(ValidationError):
        BusinessMetrics(
            order_volume=120,
            revenue_usd=5400.0,
            checkout_success_rate=120.0,  # Invalid
            cart_abandonment_rate=18.4,
        )


def test_telemetry_snapshot_roundtrip():
    """Verify full TelemetrySnapshot serialization & deserialization."""
    now = datetime.now(timezone.utc)
    snapshot = TelemetrySnapshot(
        timestamp=now,
        trace_id="tr-test-12345",
        service_id="checkout-service",
        infrastructure=InfrastructureMetrics(
            cpu_percent=40.0,
            memory_percent=55.0,
            disk_io_mbps=15.0,
            network_egress_mbps=45.0,
            network_ingress_mbps=25.0,
        ),
        application=ApplicationMetrics(
            service_id="checkout-service",
            endpoint="/api/v1/checkout",
            requests_per_sec=120.0,
            latency_p50_ms=22.0,
            latency_p95_ms=58.0,
            latency_p99_ms=95.0,
            http_2xx_count=1180,
            http_4xx_count=15,
            http_5xx_count=5,
        ),
        database=DatabaseMetrics(
            db_instance_id="aurora-postgres-primary",
            active_connections=28,
            connection_pool_utilization=38.0,
            query_latency_mean_ms=7.5,
            slow_queries_per_sec=0.05,
            row_lock_waits=0,
        ),
        business=BusinessMetrics(
            order_volume=18,
            revenue_usd=810.0,
            checkout_success_rate=99.1,
            cart_abandonment_rate=17.5,
        ),
        ground_truth_label=AnomalyArchetype.NOMINAL,
        ground_truth_anomalous=False,
    )

    dumped = snapshot.model_dump(mode="json")
    reloaded = TelemetrySnapshot.model_validate(dumped)
    assert reloaded.trace_id == "tr-test-12345"
    assert reloaded.infrastructure.cpu_percent == 40.0
    assert reloaded.application.error_rate == pytest.approx(5 / 1200, rel=1e-3)


def test_incident_create_and_remediation():
    """Verify IncidentCreate and RemediationProposal validation."""
    inc = IncidentCreate(
        title="Database Connection Pool Exhaustion on Aurora Primary",
        severity=IncidentSeverity.CRITICAL,
        service_id="checkout-service",
        summary="High 500 error rates caused by connection pool saturation.",
        correlated_signals=["db_pool_utilization > 95%", "http_5xx_rate > 35%"],
        root_cause_hypothesis="Connection leak in checkout-service database client pool",
        confidence_score=0.96,
        grounded_citations=[{"runbook": "rb-db-001.md", "section": "Connection Pool Tuning"}],
    )
    assert inc.severity == IncidentSeverity.CRITICAL
    assert inc.confidence_score == 0.96

    rem = RemediationProposal(
        incident_id="inc-123",
        action_type="INCREASE_POOL",
        target_resource="aurora-postgres-pool",
        parameters={"max_connections": "200"},
        risk_level="MEDIUM",
        requires_human_approval=True,
        dry_run_simulation=True,
        justification="Temporarily expand pool from 100 to 200 while leak investigation proceeds.",
    )
    assert rem.requires_human_approval is True
    assert rem.dry_run_simulation is True
