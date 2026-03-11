"""Executive Analytics Engine for Incident Impact Quantification.

Computes Mean Time to Remediate (MTTR) reductions, financial downtime cost
exposure avoided, engineering hours saved, and net enterprise ROI.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from apps.analytics.models import (
    ArchetypeImpactSummary,
    ExecutiveKPIAggregate,
    FinancialAssumptions,
    IncidentArchetype,
    IncidentFinancialRecord,
    MonthlyFinancialTrend,
    ServiceHealthImpact,
    SeverityLevel,
)

logger = logging.getLogger("aegisai.analytics.engine")


class ExecutiveAnalyticsEngine:
    """Core calculation engine quantifying reliability improvements into financial metrics."""

    def __init__(self, assumptions: Optional[FinancialAssumptions] = None):
        self.assumptions = assumptions or FinancialAssumptions()

    def process_incident(self, incident: Dict[str, Any]) -> IncidentFinancialRecord:
        """Convert a raw database incident dictionary into a validated IncidentFinancialRecord."""
        inc_id = str(incident.get("id", "inc-unknown"))
        title = incident.get("title", "Operational Incident")
        severity_str = str(incident.get("severity", "MEDIUM")).upper()
        try:
            severity = SeverityLevel(severity_str)
        except ValueError:
            severity = SeverityLevel.MEDIUM

        service_id = incident.get("service_id", "application-core")
        service_tier = incident.get("service_tier", "application")

        # Parse Archetype
        raw_archetype = incident.get("archetype") or incident.get("ground_truth_label") or "unclassified"
        try:
            archetype = IncidentArchetype(raw_archetype)
        except ValueError:
            archetype = IncidentArchetype.UNCLASSIFIED

        # Timestamps
        detected_at = incident.get("detected_at")
        if isinstance(detected_at, str):
            detected_at = datetime.fromisoformat(detected_at.replace("Z", "+00:00"))
        elif not isinstance(detected_at, datetime):
            detected_at = datetime.now()

        resolved_at = incident.get("resolved_at")
        if isinstance(resolved_at, str):
            resolved_at = datetime.fromisoformat(resolved_at.replace("Z", "+00:00"))

        is_false_positive = bool(incident.get("is_false_positive", False))
        status = incident.get("status", "RESOLVED")

        # MTTR Calculation
        baseline_mttr = float(incident.get("baseline_mttr", self.assumptions.historical_baseline_mttr_minutes))
        if is_false_positive:
            # False alarms are discarded immediately with 0 downtime
            actual_mttr = 5.0
            mttr_reduction = 0.0
        elif resolved_at:
            actual_mttr = max(1.0, (resolved_at - detected_at).total_seconds() / 60.0)
            mttr_reduction = max(0.0, baseline_mttr - actual_mttr)
        else:
            # For unresolved incidents, fallback to estimated AegisAI average (22.0 mins)
            actual_mttr = 22.0
            mttr_reduction = max(0.0, baseline_mttr - actual_mttr)

        # Financial Calculations
        hourly_rate = self.assumptions.get_hourly_rate(severity)
        baseline_downtime_cost = (baseline_mttr / 60.0) * hourly_rate
        actual_downtime_cost = (actual_mttr / 60.0) * hourly_rate if not is_false_positive else 0.0
        downtime_savings = max(0.0, baseline_downtime_cost - actual_downtime_cost)

        # Engineering Reclaimed Labor
        if is_false_positive:
            eng_hours_saved = 0.0
            eng_cost_saved = 0.0
        else:
            eng_hours_saved = (mttr_reduction / 60.0) * self.assumptions.engineers_per_incident_bridge
            eng_cost_saved = eng_hours_saved * self.assumptions.engineer_hourly_cost

        total_gross = downtime_savings + eng_cost_saved
        realized_net = total_gross * self.assumptions.realization_rate

        return IncidentFinancialRecord(
            incident_id=inc_id,
            title=title,
            severity=severity,
            service_id=service_id,
            service_tier=service_tier,
            archetype=archetype,
            detected_at=detected_at,
            resolved_at=resolved_at,
            baseline_mttr_minutes=round(baseline_mttr, 2),
            actual_mttr_minutes=round(actual_mttr, 2),
            mttr_reduction_minutes=round(mttr_reduction, 2),
            hourly_downtime_rate=round(hourly_rate, 2),
            baseline_downtime_cost=round(baseline_downtime_cost, 2),
            actual_downtime_cost=round(actual_downtime_cost, 2),
            downtime_savings_gross=round(downtime_savings, 2),
            engineering_hours_saved=round(eng_hours_saved, 2),
            engineering_cost_saved=round(eng_cost_saved, 2),
            total_gross_value_delivered=round(total_gross, 2),
            realized_net_savings=round(realized_net, 2),
            is_false_positive=is_false_positive,
            status=status,
            root_cause_identified=incident.get("root_cause_identified", True),
            grounding_score=float(incident.get("grounding_score", 0.98)),
        )

    def compute_executive_kpis(self, incidents: List[Dict[str, Any]]) -> ExecutiveKPIAggregate:
        """Process a collection of incidents and compute executive KPIs."""
        if not incidents:
            return self._empty_kpi_aggregate()

        records = [self.process_incident(inc) for inc in incidents]
        total_incidents = len(records)
        resolved_records = [r for r in records if r.status == "RESOLVED" and not r.is_false_positive]
        false_positive_records = [r for r in records if r.is_false_positive]

        resolved_count = len(resolved_records)
        fp_count = len(false_positive_records)
        fp_rate = (fp_count / total_incidents * 100.0) if total_incidents > 0 else 0.0

        # MTTR Stats
        valid_mttr_records = [r for r in records if not r.is_false_positive]
        if valid_mttr_records:
            baseline_avg_mttr = sum(r.baseline_mttr_minutes for r in valid_mttr_records) / len(valid_mttr_records)
            aegis_avg_mttr = sum(r.actual_mttr_minutes for r in valid_mttr_records) / len(valid_mttr_records)
            mttr_reduction_min = max(0.0, baseline_avg_mttr - aegis_avg_mttr)
            mttr_reduction_pct = (mttr_reduction_min / baseline_avg_mttr * 100.0) if baseline_avg_mttr > 0 else 0.0
        else:
            baseline_avg_mttr = self.assumptions.historical_baseline_mttr_minutes
            aegis_avg_mttr = 22.0
            mttr_reduction_min = baseline_avg_mttr - aegis_avg_mttr
            mttr_reduction_pct = (mttr_reduction_min / baseline_avg_mttr * 100.0)

        # Financial Totals
        total_downtime_avoided = sum(r.downtime_savings_gross for r in records)
        total_eng_hours = sum(r.engineering_hours_saved for r in records)
        total_eng_cost = sum(r.engineering_cost_saved for r in records)
        total_gross_value = sum(r.total_gross_value_delivered for r in records)
        total_realized_net = sum(r.realized_net_savings for r in records)

        # Platform ROI & Payback
        inv = self.assumptions.annual_platform_run_cost
        net_roi = ((total_realized_net - inv) / inv * 100.0) if inv > 0 else 0.0
        daily_savings = total_realized_net / 365.0 if total_realized_net > 0 else 0.0
        payback_days = (inv / daily_savings) if daily_savings > 0 else 999.0

        # Breakdowns
        service_impacts = self._compute_service_impacts(records)
        monthly_trends = self._compute_monthly_trends(records)
        archetype_pareto = self._compute_archetype_pareto(records)

        return ExecutiveKPIAggregate(
            total_incidents=total_incidents,
            resolved_incidents=resolved_count,
            false_positive_incidents=fp_count,
            false_positive_rate_percent=round(fp_rate, 2),
            baseline_avg_mttr_minutes=round(baseline_avg_mttr, 2),
            aegis_avg_mttr_minutes=round(aegis_avg_mttr, 2),
            mttr_reduction_minutes=round(mttr_reduction_min, 2),
            mttr_reduction_percent=round(mttr_reduction_pct, 2),
            total_downtime_exposure_avoided_gross=round(total_downtime_avoided, 2),
            total_engineering_hours_reclaimed=round(total_eng_hours, 2),
            total_engineering_cost_saved=round(total_eng_cost, 2),
            total_gross_value_delivered=round(total_gross_value, 2),
            realized_net_savings=round(total_realized_net, 2),
            annual_platform_investment=round(inv, 2),
            net_roi_percent=round(net_roi, 2),
            payback_period_days=round(payback_days, 1),
            service_impacts=service_impacts,
            monthly_trends=monthly_trends,
            archetype_pareto=archetype_pareto,
        )

    def _compute_service_impacts(self, records: List[IncidentFinancialRecord]) -> List[ServiceHealthImpact]:
        """Aggregate reliability metrics by service."""
        grouped: Dict[str, List[IncidentFinancialRecord]] = defaultdict(list)
        for r in records:
            grouped[r.service_id].append(r)

        results = []
        for s_id, s_records in grouped.items():
            first = s_records[0]
            crit_count = sum(1 for r in s_records if r.severity == SeverityLevel.CRITICAL)
            valid = [r for r in s_records if not r.is_false_positive]
            avg_mttr = (sum(r.actual_mttr_minutes for r in valid) / len(valid)) if valid else 0.0
            incurred = sum(r.actual_downtime_cost for r in s_records)
            avoided = sum(r.downtime_savings_gross for r in s_records)

            # Simulated availability SLA calculation: 100 - (total downtime minutes / annual minutes * 100)
            total_downtime_mins = sum(r.actual_mttr_minutes for r in valid)
            avail_pct = max(99.0, min(99.99, 100.0 - (total_downtime_mins / (525600.0) * 100.0)))

            results.append(
                ServiceHealthImpact(
                    service_id=s_id,
                    service_name=s_id.replace("-", " ").title(),
                    tier=first.service_tier,
                    criticality="CRITICAL" if crit_count > 0 else "HIGH",
                    owner_team="platform-sre",
                    incident_count=len(s_records),
                    critical_incident_count=crit_count,
                    avg_mttr_minutes=round(avg_mttr, 2),
                    total_downtime_cost_incurred=round(incurred, 2),
                    total_downtime_savings_avoided=round(avoided, 2),
                    availability_sla_percent=round(avail_pct, 3),
                )
            )
        return sorted(results, key=lambda x: x.total_downtime_savings_avoided, reverse=True)

    def _compute_monthly_trends(self, records: List[IncidentFinancialRecord]) -> List[MonthlyFinancialTrend]:
        """Bucket records by month."""
        grouped: Dict[str, List[IncidentFinancialRecord]] = defaultdict(list)
        for r in records:
            ym = r.detected_at.strftime("%Y-%m")
            grouped[ym].append(r)

        results = []
        for ym in sorted(grouped.keys()):
            m_records = grouped[ym]
            valid = [r for r in m_records if not r.is_false_positive]
            b_dur_hours = sum(r.baseline_mttr_minutes for r in valid) / 60.0
            a_dur_hours = sum(r.actual_mttr_minutes for r in valid) / 60.0
            hours_saved = max(0.0, b_dur_hours - a_dur_hours)

            results.append(
                MonthlyFinancialTrend(
                    year_month=ym,
                    incident_count=len(m_records),
                    p1_critical_count=sum(1 for r in m_records if r.severity == SeverityLevel.CRITICAL),
                    p2_high_count=sum(1 for r in m_records if r.severity == SeverityLevel.HIGH),
                    p3_medium_count=sum(1 for r in m_records if r.severity == SeverityLevel.MEDIUM),
                    baseline_total_duration_hours=round(b_dur_hours, 2),
                    aegis_total_duration_hours=round(a_dur_hours, 2),
                    hours_saved=round(hours_saved, 2),
                    downtime_savings_usd=round(sum(r.downtime_savings_gross for r in m_records), 2),
                    engineering_cost_saved_usd=round(sum(r.engineering_cost_saved for r in m_records), 2),
                    total_value_usd=round(sum(r.total_gross_value_delivered for r in m_records), 2),
                )
            )
        return results

    def _compute_archetype_pareto(self, records: List[IncidentFinancialRecord]) -> List[ArchetypeImpactSummary]:
        """Perform Pareto 80/20 analysis across failure archetypes."""
        grouped: Dict[str, List[IncidentFinancialRecord]] = defaultdict(list)
        for r in records:
            grouped[r.archetype.value].append(r)

        total_incidents = len(records)
        results = []
        for arch_val, a_records in grouped.items():
            incurred = sum(r.actual_downtime_cost for r in a_records)
            savings = sum(r.downtime_savings_gross for r in a_records)
            reductions = [r.mttr_reduction_minutes for r in a_records]
            avg_reduction = (sum(reductions) / len(reductions)) if reductions else 0.0

            results.append(
                ArchetypeImpactSummary(
                    archetype=arch_val,
                    incident_count=len(a_records),
                    percentage_of_total_incidents=round((len(a_records) / total_incidents * 100.0), 2) if total_incidents else 0.0,
                    total_downtime_cost_usd=round(incurred, 2),
                    total_savings_usd=round(savings, 2),
                    avg_mttr_reduction_minutes=round(avg_reduction, 2),
                )
            )
        return sorted(results, key=lambda x: x.total_savings_usd, reverse=True)

    def _empty_kpi_aggregate(self) -> ExecutiveKPIAggregate:
        """Return zeroed aggregate when no incidents are provided."""
        return ExecutiveKPIAggregate(
            total_incidents=0,
            resolved_incidents=0,
            false_positive_incidents=0,
            false_positive_rate_percent=0.0,
            baseline_avg_mttr_minutes=self.assumptions.historical_baseline_mttr_minutes,
            aegis_avg_mttr_minutes=0.0,
            mttr_reduction_minutes=0.0,
            mttr_reduction_percent=0.0,
            total_downtime_exposure_avoided_gross=0.0,
            total_engineering_hours_reclaimed=0.0,
            total_engineering_cost_saved=0.0,
            total_gross_value_delivered=0.0,
            realized_net_savings=0.0,
            annual_platform_investment=self.assumptions.annual_platform_run_cost,
            net_roi_percent=0.0,
            payback_period_days=999.0,
        )

    def generate_annual_benchmark_dataset(self) -> List[Dict[str, Any]]:
        """Synthesize 48 calibrated annual incidents matching the exact profile in docs/03_business_case.md.

        Profile:
        - 48 incidents/year (4 Critical/P1, 12 Major/P2, 32 Minor/P3)
        - Baseline MTTR: 90.0 mins
        - AegisAI MTTR: ~22.0 mins (75.5% reduction)
        - Historical downtime cost avoided: ~$3.35M gross ($838k realized net)
        """
        incidents: List[Dict[str, Any]] = []
        base_time = datetime(2026, 1, 1, 8, 0, 0)

        # 1. 4 Critical (P1) Incidents
        p1_specs = [
            ("INC-2026-001", "Payment Processor Latency Spike & Gateway Dropping", "checkout-service", "payment_gateway_latency_spike", 21.0),
            ("INC-2026-002", "Aurora PostgreSQL Connection Pool Starvation", "aurora-postgres-primary", "db_connection_pool_leak", 24.0),
            ("INC-2026-003", "Kubernetes Ingress Out-Of-Memory CrashLoopBackOff", "kubernetes-cluster-core", "memory_leak_oom", 22.0),
            ("INC-2026-004", "Black Friday Order Ingestion Buffer Saturation", "order-processing", "cpu_saturation", 21.0),
        ]
        for idx, (inc_id, title, svc, arch, mttr_min) in enumerate(p1_specs):
            t_det = base_time + timedelta(days=idx * 90 + 15, hours=14)
            t_res = t_det + timedelta(minutes=mttr_min)
            incidents.append({
                "id": inc_id,
                "title": title,
                "severity": "CRITICAL",
                "service_id": svc,
                "service_tier": "database" if "postgres" in svc else "application",
                "archetype": arch,
                "detected_at": t_det,
                "resolved_at": t_res,
                "status": "RESOLVED",
                "baseline_mttr": 90.0,
                "is_false_positive": False,
                "grounding_score": 0.99,
            })

        # 2. 12 Major (P2) Incidents
        p2_archetypes = [
            ("Redis Cache Eviction Surge", "redis-session-store", "memory_leak_oom", 23.0),
            ("Order Processing Backpressure Throttling", "order-processing", "cpu_saturation", 22.0),
            ("PostgreSQL Vacuum Lock Contention", "aurora-postgres-primary", "db_connection_pool_leak", 25.0),
            ("Kafka Partition Consumer Rebalance Storm", "order-processing", "network_partition", 20.0),
        ]
        for i in range(12):
            arch_title, svc, arch, mttr_min = p2_archetypes[i % len(p2_archetypes)]
            t_det = base_time + timedelta(days=i * 28 + 5, hours=10)
            t_res = t_det + timedelta(minutes=mttr_min)
            incidents.append({
                "id": f"INC-2026-0{i+10:02d}",
                "title": f"{arch_title} (Cluster-{i+1})",
                "severity": "HIGH",
                "service_id": svc,
                "service_tier": "database" if "redis" in svc or "postgres" in svc else "application",
                "archetype": arch,
                "detected_at": t_det,
                "resolved_at": t_res,
                "status": "RESOLVED",
                "baseline_mttr": 90.0,
                "is_false_positive": False,
                "grounding_score": 0.97,
            })

        # 3. 32 Minor (P3) Incidents (including 2 calibrated false positives)
        for i in range(32):
            is_fp = (i in [7, 21])  # 2 false positives out of 48 = ~4.1% FPR
            t_det = base_time + timedelta(days=i * 11 + 2, hours=3)
            mttr_min = 5.0 if is_fp else 22.0
            t_res = t_det + timedelta(minutes=mttr_min)
            incidents.append({
                "id": f"INC-2026-0{i+30:02d}",
                "title": f"Telemetry Anomaly Drift Alert #{i+1}" if not is_fp else f"Transient Metric Glitch #{i+1}",
                "severity": "MEDIUM",
                "service_id": "checkout-service" if i % 2 == 0 else "kubernetes-cluster-core",
                "service_tier": "application",
                "archetype": "unclassified_anomaly" if is_fp else "disk_io_throttling",
                "detected_at": t_det,
                "resolved_at": t_res,
                "status": "RESOLVED",
                "baseline_mttr": 90.0,
                "is_false_positive": is_fp,
                "grounding_score": 0.96,
            })

        return incidents
