"""Data Models for AegisAI Executive Analytics & Business Impact Layer.

Implements financial data structures, MTTR calculations, revenue exposure,
and Star-Schema-ready analytics entities for Power BI and Tableau.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class SeverityLevel(str, Enum):
    """Incident severity classification."""
    CRITICAL = "CRITICAL"  # P1
    HIGH = "HIGH"          # P2
    MEDIUM = "MEDIUM"      # P3
    LOW = "LOW"            # P4


class IncidentArchetype(str, Enum):
    """Categorized recurring failure archetypes."""
    DB_POOL_EXHAUSTION = "db_connection_pool_leak"
    MEMORY_LEAK_OOM = "memory_leak_oom"
    PAYMENT_GATEWAY_TIMEOUT = "payment_gateway_latency_spike"
    CPU_SATURATION = "cpu_saturation"
    DISK_IO_THROTTLING = "disk_io_throttling"
    NETWORK_PARTITION = "network_partition"
    UNCLASSIFIED = "unclassified_anomaly"


class FinancialAssumptions(BaseModel):
    """Actuarial and financial modeling assumptions (grounded in docs/03_business_case.md)."""
    # Hourly downtime cost by severity tier
    downtime_rate_critical: float = Field(default=180000.0, description="Cost per hour of Critical/P1 downtime ($)")
    downtime_rate_high: float = Field(default=120000.0, description="Cost per hour of High/P2 downtime ($)")
    downtime_rate_medium: float = Field(default=25000.0, description="Cost per hour of Medium/P3 downtime ($)")
    downtime_rate_low: float = Field(default=5000.0, description="Cost per hour of Low/P4 downtime ($)")

    # Engineering labor rates
    engineer_hourly_cost: float = Field(default=95.0, description="Fully burdened hourly rate per SRE/Software Engineer ($)")
    engineers_per_incident_bridge: int = Field(default=3, description="Average number of engineers on incident triage bridge")

    # Platform baseline & realization
    historical_baseline_mttr_minutes: float = Field(default=90.0, description="Industry/Historical baseline MTTR before AegisAI (mins)")
    annual_platform_run_cost: float = Field(default=15000.0, description="Annual infrastructure and platform operational cost ($)")
    realization_rate: float = Field(default=0.25, description="Conservative realization factor applied to downtime savings (25%)")

    def get_hourly_rate(self, severity: SeverityLevel) -> float:
        """Return the downtime cost per hour for the given severity."""
        if severity == SeverityLevel.CRITICAL:
            return self.downtime_rate_critical
        elif severity == SeverityLevel.HIGH:
            return self.downtime_rate_high
        elif severity == SeverityLevel.MEDIUM:
            return self.downtime_rate_medium
        return self.downtime_rate_low


class IncidentFinancialRecord(BaseModel):
    """Detailed financial record for an individual incident (Fact Table entity)."""
    incident_id: str
    title: str
    severity: SeverityLevel
    service_id: str
    service_tier: str = "application"
    archetype: IncidentArchetype = IncidentArchetype.UNCLASSIFIED
    detected_at: datetime
    resolved_at: Optional[datetime] = None

    # MTTR Metrics (in minutes)
    baseline_mttr_minutes: float
    actual_mttr_minutes: float
    mttr_reduction_minutes: float

    # Financial Exposure & Savings (in USD)
    hourly_downtime_rate: float
    baseline_downtime_cost: float
    actual_downtime_cost: float
    downtime_savings_gross: float

    # Engineering Labor Reclaimed
    engineering_hours_saved: float
    engineering_cost_saved: float

    # Total Value Delivered
    total_gross_value_delivered: float
    realized_net_savings: float

    # Governance & Verification
    is_false_positive: bool = False
    status: str = "RESOLVED"
    root_cause_identified: bool = True
    grounding_score: float = 1.0


class ServiceHealthImpact(BaseModel):
    """Aggregated reliability and financial impact per microservice."""
    service_id: str
    service_name: str
    tier: str
    criticality: str
    owner_team: str
    incident_count: int
    critical_incident_count: int
    avg_mttr_minutes: float
    total_downtime_cost_incurred: float
    total_downtime_savings_avoided: float
    availability_sla_percent: float


class MonthlyFinancialTrend(BaseModel):
    """Time-bucketed financial and incident trends for executive time-series reporting."""
    year_month: str  # Format: "YYYY-MM"
    incident_count: int
    p1_critical_count: int
    p2_high_count: int
    p3_medium_count: int
    baseline_total_duration_hours: float
    aegis_total_duration_hours: float
    hours_saved: float
    downtime_savings_usd: float
    engineering_cost_saved_usd: float
    total_value_usd: float


class ArchetypeImpactSummary(BaseModel):
    """Pareto analysis entity for recurring failure archetypes."""
    archetype: str
    incident_count: int
    percentage_of_total_incidents: float
    total_downtime_cost_usd: float
    total_savings_usd: float
    avg_mttr_reduction_minutes: float


class ExecutiveKPIAggregate(BaseModel):
    """Executive KPI Summary for C-Suite, VP of Engineering, and Board Dashboards."""
    total_incidents: int
    resolved_incidents: int
    false_positive_incidents: int
    false_positive_rate_percent: float

    # MTTR Benchmarks
    baseline_avg_mttr_minutes: float
    aegis_avg_mttr_minutes: float
    mttr_reduction_minutes: float
    mttr_reduction_percent: float

    # Financial Figures (USD)
    total_downtime_exposure_avoided_gross: float
    total_engineering_hours_reclaimed: float
    total_engineering_cost_saved: float
    total_gross_value_delivered: float
    realized_net_savings: float

    # Investment & Return on Investment (ROI)
    annual_platform_investment: float
    net_roi_percent: float
    payback_period_days: float

    # Category Breakdowns
    service_impacts: List[ServiceHealthImpact] = Field(default_factory=list)
    monthly_trends: List[MonthlyFinancialTrend] = Field(default_factory=list)
    archetype_pareto: List[ArchetypeImpactSummary] = Field(default_factory=list)
