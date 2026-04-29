"""Unit and Integration Tests for Executive Analytics & Business Impact Layer (Phase 13).

Validates:
- Actuarial and financial downtime calculations
- MTTR compression and labor hours reclaimed
- Power BI and Tableau BI exporters (CSV, JSON, Markdown)
- Star Schema view compatibility
- FastAPI Analytics router endpoints
- Analytics CLI tool
"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.analytics.cli import cmd_generate, cmd_kpis, cmd_report
from apps.analytics.engine import ExecutiveAnalyticsEngine
from apps.analytics.exporter import BIExporter
from apps.analytics.models import (
    FinancialAssumptions,
    IncidentArchetype,
    SeverityLevel,
)
from apps.api.main import create_app


@pytest.fixture
def analytics_engine() -> ExecutiveAnalyticsEngine:
    return ExecutiveAnalyticsEngine()


@pytest.fixture
def sample_incident_data() -> dict:
    t_det = datetime(2026, 3, 15, 10, 0, 0)
    t_res = t_det + timedelta(minutes=20)
    return {
        "id": "INC-TEST-001",
        "title": "Database Connection Pool Exhaustion",
        "severity": "CRITICAL",
        "service_id": "aurora-postgres-primary",
        "service_tier": "database",
        "archetype": "db_connection_pool_leak",
        "detected_at": t_det,
        "resolved_at": t_res,
        "status": "RESOLVED",
        "baseline_mttr": 90.0,
        "is_false_positive": False,
        "grounding_score": 0.99,
    }


class TestFinancialAssumptions:
    """Tests financial rate lookup and defaults."""

    def test_default_rates(self):
        assumptions = FinancialAssumptions()
        assert assumptions.get_hourly_rate(SeverityLevel.CRITICAL) == 180000.0
        assert assumptions.get_hourly_rate(SeverityLevel.HIGH) == 120000.0
        assert assumptions.get_hourly_rate(SeverityLevel.MEDIUM) == 25000.0
        assert assumptions.get_hourly_rate(SeverityLevel.LOW) == 5000.0
        assert assumptions.historical_baseline_mttr_minutes == 90.0
        assert assumptions.realization_rate == 0.25


class TestExecutiveAnalyticsEngine:
    """Tests accuracy of MTTR, downtime cost, and ROI algorithms."""

    def test_process_critical_incident(self, analytics_engine: ExecutiveAnalyticsEngine, sample_incident_data: dict):
        record = analytics_engine.process_incident(sample_incident_data)

        # Baseline: 90 mins @ $180,000/hr = $270,000
        assert record.baseline_mttr_minutes == 90.0
        assert record.baseline_downtime_cost == 270000.0

        # Actual: 20 mins @ $180,000/hr = $60,000
        assert record.actual_mttr_minutes == 20.0
        assert record.actual_downtime_cost == 60000.0

        # Downtime Savings: $210,000
        assert record.mttr_reduction_minutes == 70.0
        assert record.downtime_savings_gross == 210000.0

        # Engineering labor: (70 / 60) * 3 engineers = 3.5 hrs; 3.5 * $95 = $332.50
        assert record.engineering_hours_saved == pytest.approx(3.5, rel=1e-2)
        assert record.engineering_cost_saved == pytest.approx(332.50, rel=1e-2)

        # Realized net (25% model)
        total_gross = 210000.0 + 332.50
        assert record.total_gross_value_delivered == pytest.approx(total_gross, rel=1e-2)
        assert record.realized_net_savings == pytest.approx(total_gross * 0.25, rel=1e-2)

    def test_process_false_positive_incident(self, analytics_engine: ExecutiveAnalyticsEngine):
        fp_data = {
            "id": "INC-FP-001",
            "title": "Spurious CPU spike alert",
            "severity": "MEDIUM",
            "service_id": "checkout-service",
            "detected_at": datetime.now(),
            "is_false_positive": True,
            "status": "DISCARDED",
        }
        record = analytics_engine.process_incident(fp_data)
        assert record.is_false_positive is True
        assert record.actual_downtime_cost == 0.0
        assert record.engineering_hours_saved == 0.0
        assert record.archetype == IncidentArchetype.UNCLASSIFIED

    def test_compute_executive_kpis_empty(self, analytics_engine: ExecutiveAnalyticsEngine):
        kpi = analytics_engine.compute_executive_kpis([])
        assert kpi.total_incidents == 0
        assert kpi.net_roi_percent == 0.0

    def test_annual_benchmark_dataset_metrics(self, analytics_engine: ExecutiveAnalyticsEngine):
        dataset = analytics_engine.generate_annual_benchmark_dataset()
        assert len(dataset) == 48

        kpi = analytics_engine.compute_executive_kpis(dataset)
        assert kpi.total_incidents == 48
        assert kpi.resolved_incidents == 46
        assert kpi.false_positive_incidents == 2
        assert kpi.false_positive_rate_percent == pytest.approx(4.17, abs=0.1)

        # MTTR reduced from 90 to ~22 mins (>= 75% drop)
        assert kpi.baseline_avg_mttr_minutes == 90.0
        assert 21.0 <= kpi.aegis_avg_mttr_minutes <= 23.0
        assert kpi.mttr_reduction_percent >= 74.0

        # Financial impact
        assert kpi.total_downtime_exposure_avoided_gross > 3000000.0
        assert kpi.realized_net_savings > 750000.0
        assert kpi.net_roi_percent > 4000.0
        assert kpi.payback_period_days < 15.0

        # Breakdowns present
        assert len(kpi.service_impacts) >= 4
        assert len(kpi.monthly_trends) >= 10
        assert len(kpi.archetype_pareto) >= 5


class TestBIExporter:
    """Tests file generation for Power BI and Tableau."""

    def test_export_all_creates_valid_artifacts(self, tmp_path: Path, analytics_engine: ExecutiveAnalyticsEngine):
        exporter = BIExporter(export_dir=tmp_path)
        dataset = analytics_engine.generate_annual_benchmark_dataset()
        records = [analytics_engine.process_incident(inc) for inc in dataset]
        aggregate = analytics_engine.compute_executive_kpis(dataset)

        exported = exporter.export_all(records, aggregate)

        # 1. Fact table CSV
        fact_csv = exported["fact_incident_financials"]
        assert fact_csv.exists()
        lines = fact_csv.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 49  # Header + 48 rows
        assert "incident_id,date_key,timestamp" in lines[0]

        # 2. Dimensions CSV
        dim_svc = exported["dim_service"]
        assert dim_svc.exists()
        assert "checkout-service" in dim_svc.read_text(encoding="utf-8")

        dim_sev = exported["dim_severity"]
        assert dim_sev.exists()
        assert "CRITICAL" in dim_sev.read_text(encoding="utf-8")

        dim_arch = exported["dim_archetype"]
        assert dim_arch.exists()
        assert "db_connection_pool_leak" in dim_arch.read_text(encoding="utf-8")

        # 3. JSON Summary
        summary_json = exported["executive_summary_json"]
        assert summary_json.exists()
        content = summary_json.read_text(encoding="utf-8")
        assert '"total_incidents": 48' in content
        assert '"net_roi_percent":' in content

        # 4. Markdown Report
        report_md = exported["executive_roi_report"]
        assert report_md.exists()
        md_text = report_md.read_text(encoding="utf-8")
        assert "AegisAI: Executive Reliability & Business Impact Report" in md_text
        assert "Mean Time to Remediate (MTTR)" in md_text


class TestAnalyticsAPIRouter:
    """Validates FastAPI analytics endpoints."""

    @pytest.fixture
    def client(self):
        app = create_app()
        return TestClient(app)

    def test_get_executive_kpis_endpoint(self, client: TestClient):
        response = client.get("/v1/analytics/kpis")
        assert response.status_code == 200
        data = response.json()
        assert data["total_incidents"] == 48
        assert data["mttr_reduction_percent"] >= 74.0
        assert data["realized_net_savings"] > 500000.0

    def test_get_financial_impact_endpoint(self, client: TestClient):
        response = client.get("/v1/analytics/financial-impact")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "total_downtime_exposure_avoided_gross_usd" in data
        assert data["hourly_rates"]["critical_p1"] == 180000.0

    def test_list_incidents_endpoint(self, client: TestClient):
        response = client.get("/v1/analytics/incidents")
        assert response.status_code == 200
        records = response.json()
        assert len(records) == 48

        # Filtering by severity
        filtered_resp = client.get("/v1/analytics/incidents?severity=CRITICAL")
        assert filtered_resp.status_code == 200
        crit_records = filtered_resp.json()
        assert len(crit_records) == 4
        assert all(r["severity"] == "CRITICAL" for r in crit_records)

    def test_export_csv_endpoint(self, client: TestClient):
        response = client.get("/v1/analytics/export/csv")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        text = response.text
        assert text.startswith("incident_id,date_key,timestamp")
        assert len(text.strip().splitlines()) == 49


class TestAnalyticsCLI:
    """Validates CLI command line functions."""

    def test_cmd_generate(self, tmp_path: Path, capsys):
        cmd_generate(out_dir=str(tmp_path / "cli_export"))
        captured = capsys.readouterr()
        assert "AegisAI Executive Analytics Generator" in captured.out
        assert "Executive Analytics generation completed successfully" in captured.out

    def test_cmd_kpis(self, capsys):
        cmd_kpis()
        captured = capsys.readouterr()
        assert "AEGISAI EXECUTIVE BOARD SCORECARD" in captured.out
        assert "Mean Time to Remediate" in captured.out

    def test_cmd_report(self, capsys):
        cmd_report()
        captured = capsys.readouterr()
        assert "AegisAI: Executive Reliability & Business Impact Report" in captured.out
