"""FastAPI Analytics & Business Impact Router.

Exposes executive KPI summaries, MTTR reductions, financial exposure avoided,
and streaming CSV endpoints for Power BI and Tableau web connectors.
"""

import io
from typing import List, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, StreamingResponse

from apps.analytics.engine import ExecutiveAnalyticsEngine
from apps.analytics.models import (
    ExecutiveKPIAggregate,
    IncidentFinancialRecord,
    SeverityLevel,
)

router = APIRouter(prefix="/v1/analytics", tags=["Executive Analytics"])

# Default singleton analytics engine for API queries
_analytics_engine = ExecutiveAnalyticsEngine()
_benchmark_dataset = _analytics_engine.generate_annual_benchmark_dataset()


@router.get(
    "/kpis",
    response_model=ExecutiveKPIAggregate,
    summary="Get Executive Board Scorecard & KPIs",
    description="Returns high-level reliability metrics: MTTR compression, downtime avoided, reclaimed engineering labor, and net ROI.",
)
async def get_executive_kpis() -> ExecutiveKPIAggregate:
    """Return aggregated executive reliability and financial KPIs."""
    return _analytics_engine.compute_executive_kpis(_benchmark_dataset)


@router.get(
    "/financial-impact",
    summary="Get Financial Exposure Avoided Breakdown",
    description="Returns financial downtime savings by service tier and failure archetype.",
)
async def get_financial_impact() -> JSONResponse:
    """Return financial breakdown and ROI parameters."""
    aggregate = _analytics_engine.compute_executive_kpis(_benchmark_dataset)
    return JSONResponse(
        content={
            "status": "success",
            "annual_platform_investment_usd": aggregate.annual_platform_investment,
            "total_downtime_exposure_avoided_gross_usd": aggregate.total_downtime_exposure_avoided_gross,
            "total_engineering_cost_saved_usd": aggregate.total_engineering_cost_saved,
            "total_gross_value_delivered_usd": aggregate.total_gross_value_delivered,
            "realized_net_savings_usd": aggregate.realized_net_savings,
            "net_roi_percent": aggregate.net_roi_percent,
            "payback_period_days": aggregate.payback_period_days,
            "hourly_rates": {
                "critical_p1": _analytics_engine.assumptions.downtime_rate_critical,
                "high_p2": _analytics_engine.assumptions.downtime_rate_high,
                "medium_p3": _analytics_engine.assumptions.downtime_rate_medium,
                "low_p4": _analytics_engine.assumptions.downtime_rate_low,
            },
        }
    )


@router.get(
    "/incidents",
    response_model=List[IncidentFinancialRecord],
    summary="List Individual Incident Financial Records",
    description="Returns granular fact records per incident with financial and MTTR metrics.",
)
async def list_incident_financials(
    severity: Optional[SeverityLevel] = Query(None, description="Filter by severity level"),
    service_id: Optional[str] = Query(None, description="Filter by service ID"),
) -> List[IncidentFinancialRecord]:
    """Return filtered list of incident financial records."""
    records = [_analytics_engine.process_incident(inc) for inc in _benchmark_dataset]

    if severity:
        records = [r for r in records if r.severity == severity]
    if service_id:
        records = [r for r in records if r.service_id == service_id]

    return records


@router.get(
    "/export/csv",
    summary="Export Fact Table as CSV",
    description="Streams fact_incident_financials.csv directly for Power BI Web Connector and Tableau Web Data Connector.",
)
async def export_fact_table_csv() -> StreamingResponse:
    """Stream CSV table for external BI consumers."""
    records = [_analytics_engine.process_incident(inc) for inc in _benchmark_dataset]

    # Create in-memory buffer
    import csv
    output = io.StringIO()
    fieldnames = [
        "incident_id",
        "date_key",
        "timestamp",
        "service_id",
        "service_tier",
        "severity",
        "archetype",
        "baseline_mttr_minutes",
        "actual_mttr_minutes",
        "mttr_reduction_minutes",
        "hourly_downtime_rate",
        "baseline_downtime_cost",
        "actual_downtime_cost",
        "downtime_savings_gross",
        "engineering_hours_saved",
        "engineering_cost_saved",
        "total_gross_value_delivered",
        "realized_net_savings",
        "is_false_positive",
        "status",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for r in records:
        writer.writerow({
            "incident_id": r.incident_id,
            "date_key": r.detected_at.strftime("%Y%m%d"),
            "timestamp": r.detected_at.isoformat(),
            "service_id": r.service_id,
            "service_tier": r.service_tier,
            "severity": r.severity.value,
            "archetype": r.archetype.value,
            "baseline_mttr_minutes": r.baseline_mttr_minutes,
            "actual_mttr_minutes": r.actual_mttr_minutes,
            "mttr_reduction_minutes": r.mttr_reduction_minutes,
            "hourly_downtime_rate": r.hourly_downtime_rate,
            "baseline_downtime_cost": r.baseline_downtime_cost,
            "actual_downtime_cost": r.actual_downtime_cost,
            "downtime_savings_gross": r.downtime_savings_gross,
            "engineering_hours_saved": r.engineering_hours_saved,
            "engineering_cost_saved": r.engineering_cost_saved,
            "total_gross_value_delivered": r.total_gross_value_delivered,
            "realized_net_savings": r.realized_net_savings,
            "is_false_positive": r.is_false_positive,
            "status": r.status,
        })
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="fact_incident_financials.csv"'},
    )
