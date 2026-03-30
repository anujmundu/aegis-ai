"""Multi-Tier Synthetic Telemetry Generator for AegisAI.

Generates realistic, physically consistent operational telemetry across 4 architectural tiers:
1. Infrastructure (Host/Container: CPU, Memory, Disk, Network)
2. Application (Microservice: Requests/sec, p50/p95/p99 Latency, HTTP 2xx/4xx/5xx)
3. Database (Relational/Cache: Pool Utilization, Query Latency, Active Connections, Row Locks)
4. Business (KPIs: Order Volume, Gross Revenue, Checkout Success Rate, Cart Abandonment)

Includes Diurnal Circadian Cycles and 5 Realistic Anomaly Archetypes:
- DB_CONNECTION_POOL_SATURATION
- MEMORY_LEAK_GC_PAUSE
- CASCADING_THIRD_PARTY_FAILURE
- PAYMENT_GATEWAY_OUTAGE
- BLACK_FRIDAY_TRAFFIC_BURST
"""

import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Generator, List, Optional

import numpy as np
import pandas as pd

from data.schemas.events import (
    AnomalyArchetype,
    ApplicationMetrics,
    BusinessMetrics,
    DatabaseMetrics,
    InfrastructureMetrics,
    TelemetrySnapshot,
)


class MultiTierTelemetryGenerator:
    """Generator for multi-tier synthetic telemetry with realistic physical correlations."""

    def __init__(
        self,
        service_id: str = "checkout-service",
        endpoint: str = "/api/v1/checkout",
        db_instance_id: str = "aurora-postgres-primary",
        sampling_interval_seconds: int = 10,
        seed: Optional[int] = 42,
    ) -> None:
        self.service_id = service_id
        self.endpoint = endpoint
        self.db_instance_id = db_instance_id
        self.sampling_interval_seconds = sampling_interval_seconds
        self.rng = np.random.default_rng(seed)
        self.current_time = datetime(2026, 10, 2, 8, 0, 0, tzinfo=timezone.utc)
        self.tick_counter = 0

        # Stateful drifts for continuous generation
        self._memory_leak_accum_mb: float = 0.0

    def reset(self, start_time: Optional[datetime] = None) -> None:
        """Reset internal state, counters, and clock."""
        self.tick_counter = 0
        self._memory_leak_accum_mb = 0.0
        self.current_time = start_time or datetime(2026, 10, 2, 8, 0, 0, tzinfo=timezone.utc)

    def _get_circadian_factor(self, dt: datetime) -> float:
        """Calculate diurnal traffic multiplier based on hour of day.

        Peak traffic is at ~15:00 UTC (1.4x), lowest trough is at ~04:00 UTC (0.6x).
        """
        hour_fraction = dt.hour + (dt.minute / 60.0) + (dt.second / 3600.0)
        # Shift peak to 15:00 UTC: sin((hour - 9) * 2pi / 24)
        circadian = math.sin((hour_fraction - 9.0) * (2.0 * math.pi / 24.0))
        # Map [-1, 1] to [0.6, 1.4]
        return 1.0 + (0.4 * circadian)

    def generate_snapshot(
        self,
        archetype: AnomalyArchetype = AnomalyArchetype.NOMINAL,
        progress: float = 1.0,
        timestamp: Optional[datetime] = None,
    ) -> TelemetrySnapshot:
        """Generate a single TelemetrySnapshot matching the specified archetype."""
        if timestamp is None:
            ts = self.current_time
            self.current_time += timedelta(seconds=self.sampling_interval_seconds)
        else:
            ts = timestamp

        self.tick_counter += 1
        circadian = self._get_circadian_factor(ts)

        # Baseline Nominal Values
        base_rps = max(10.0, float(self.rng.normal(120.0 * circadian, 8.0)))
        base_cpu = min(95.0, max(5.0, float(self.rng.normal(35.0 * circadian, 3.0))))
        base_mem = min(90.0, max(20.0, float(self.rng.normal(48.0, 1.5))))
        base_disk = max(1.0, float(self.rng.normal(18.0 * circadian, 2.5)))
        base_net_egress = max(5.0, float(self.rng.normal(52.0 * circadian, 4.0)))
        base_net_ingress = max(2.0, float(self.rng.normal(26.0 * circadian, 2.0)))

        base_p50 = max(5.0, float(self.rng.normal(24.0, 2.0)))
        base_p95 = max(base_p50 + 10.0, float(self.rng.normal(62.0, 4.0)))
        base_p99 = max(base_p95 + 15.0, float(self.rng.normal(105.0, 8.0)))

        total_requests = int(base_rps * self.sampling_interval_seconds)
        base_5xx = int(self.rng.poisson(max(0.1, total_requests * 0.001)))
        base_4xx = int(self.rng.poisson(max(1.0, total_requests * 0.015)))
        base_2xx = max(0, total_requests - base_4xx - base_5xx)

        base_db_active = int(max(5, self.rng.normal(28 * circadian, 3)))
        base_db_pool = min(100.0, max(5.0, float(self.rng.normal(38.0 * circadian, 3.0))))
        base_db_latency = max(2.0, float(self.rng.normal(8.5, 0.8)))
        base_db_slow_q = max(0.0, float(self.rng.exponential(0.1)))
        base_db_locks = int(self.rng.poisson(0.2))

        base_orders = int(max(0, self.rng.normal(total_requests * 0.14, 5)))
        base_revenue = round(float(base_orders * self.rng.uniform(42.0, 58.0)), 2)
        base_checkout_success = min(100.0, max(95.0, float(self.rng.normal(99.2, 0.3))))
        base_cart_abandonment = min(50.0, max(5.0, float(self.rng.normal(18.5, 1.2))))

        is_anomalous = archetype != AnomalyArchetype.NOMINAL
        root_cause_desc: Optional[str] = None

        # Apply Incident Archetype Dynamics
        if archetype == AnomalyArchetype.DB_CONNECTION_POOL_SATURATION:
            # Saturated pool leads to queuing, 500s, DB latency explosion, modest app CPU
            pool_factor = min(1.0, max(0.2, progress))
            base_db_pool = min(99.5, 75.0 + (24.0 * pool_factor) + float(self.rng.normal(0, 0.5)))
            base_db_active = int(98 + self.rng.integers(0, 3))
            base_db_latency = 45.0 + (320.0 * pool_factor) + float(self.rng.normal(0, 15))
            base_db_slow_q = 25.0 + (45.0 * pool_factor)
            base_db_locks = int(12 + (30 * pool_factor))

            base_p50 = 65.0 + (120.0 * pool_factor)
            base_p95 = 250.0 + (480.0 * pool_factor)
            base_p99 = 650.0 + (1450.0 * pool_factor)

            # Error rate explodes as connections timeout
            base_5xx = int(total_requests * (0.15 + (0.35 * pool_factor)))
            base_2xx = max(0, total_requests - base_4xx - base_5xx)

            base_checkout_success = max(25.0, 99.0 - (65.0 * pool_factor))
            base_cart_abandonment = min(85.0, 18.0 + (50.0 * pool_factor))
            root_cause_desc = (
                "PostgreSQL connection pool exhausted (98%+); client connections blocking on max_connections"
            )

        elif archetype == AnomalyArchetype.MEMORY_LEAK_GC_PAUSE:
            # Memory drifts upward; periodic GC causes CPU spikes and stop-the-world latency
            leak_factor = min(1.0, max(0.1, progress))
            base_mem = min(97.5, 52.0 + (43.0 * leak_factor) + float(self.rng.normal(0, 0.3)))

            # Periodic GC pause every 3 ticks when memory > 80%
            is_gc_pause = (self.tick_counter % 3 == 0) and (base_mem > 78.0)
            if is_gc_pause:
                base_cpu = min(99.5, 88.0 + float(self.rng.normal(6.0, 2.0)))
                base_p95 = 450.0 + float(self.rng.normal(120.0, 20.0))
                base_p99 = 1100.0 + float(self.rng.normal(300.0, 50.0))
            else:
                base_cpu = min(70.0, base_cpu + (10.0 * leak_factor))

            base_checkout_success = max(82.0, 99.0 - (15.0 * leak_factor))
            root_cause_desc = (
                "JVM/Python heap memory leak; recurring full garbage collection pause causing latency degradation"
            )

        elif archetype == AnomalyArchetype.CASCADING_THIRD_PARTY_FAILURE:
            # Downstream external partner latency spikes, threads exhaust, CPU is low (waiting)
            sev = min(1.0, max(0.2, progress))
            base_cpu = max(12.0, 28.0 - (12.0 * sev))  # CPU drops as worker threads block
            base_p50 = 350.0 + (600.0 * sev)
            base_p95 = 1200.0 + (2100.0 * sev)
            base_p99 = 2800.0 + (3500.0 * sev)

            # Gateway 504 timeouts surge
            base_5xx = int(total_requests * (0.30 + (0.45 * sev)))
            base_2xx = max(0, total_requests - base_4xx - base_5xx)

            base_checkout_success = max(10.0, 98.0 - (80.0 * sev))
            base_cart_abandonment = min(92.0, 20.0 + (68.0 * sev))
            root_cause_desc = (
                "Downstream third-party fraud verification API timeout cascading into thread exhaustion"
            )

        elif archetype == AnomalyArchetype.PAYMENT_GATEWAY_OUTAGE:
            # Infra & DB are 100% nominal; HTTP codes are 200 (payment rejected payload); Business KPIs drop
            base_checkout_success = max(4.0, float(self.rng.normal(8.5, 1.5)))
            base_cart_abandonment = min(96.0, float(self.rng.normal(88.0, 2.0)))
            base_orders = int(max(1, base_orders * 0.08))
            base_revenue = round(float(base_orders * 48.0), 2)
            root_cause_desc = (
                "External payment gateway outage returning HTTP 200 DECLINED payload; checkout conversion collapsed"
            )

        elif archetype == AnomalyArchetype.BLACK_FRIDAY_TRAFFIC_BURST:
            # Benign surge: 4.5x traffic, system scales gracefully, error rate stays low
            burst_factor = 4.2
            base_rps = base_rps * burst_factor
            total_requests = int(base_rps * self.sampling_interval_seconds)
            base_cpu = min(82.0, 68.0 + float(self.rng.normal(0, 3.0)))
            base_mem = min(78.0, 64.0 + float(self.rng.normal(0, 2.0)))
            base_disk = base_disk * 3.2
            base_net_egress = base_net_egress * 3.8
            base_net_ingress = base_net_ingress * 3.6

            base_p50 = 36.0 + float(self.rng.normal(0, 2.0))
            base_p95 = 92.0 + float(self.rng.normal(0, 5.0))
            base_p99 = 155.0 + float(self.rng.normal(0, 10.0))

            base_4xx = int(self.rng.poisson(total_requests * 0.012))
            base_5xx = int(self.rng.poisson(total_requests * 0.003))
            base_2xx = max(0, total_requests - base_4xx - base_5xx)

            base_db_active = int(base_db_active * 2.8)
            base_db_pool = min(78.0, base_db_pool * 1.8)
            base_db_latency = max(3.0, float(self.rng.normal(14.0, 1.2)))

            base_orders = int(base_orders * burst_factor)
            base_revenue = round(float(base_orders * 55.0), 2)
            base_checkout_success = min(99.5, max(97.5, float(self.rng.normal(98.6, 0.4))))
            is_anomalous = False  # Benign traffic surge - healthy operational scaling
            root_cause_desc = "Benign promotional traffic surge; autoscaling infrastructure absorbing load"

        trace_id = f"tr-{uuid.uuid4().hex[:12]}"

        return TelemetrySnapshot(
            timestamp=ts,
            trace_id=trace_id,
            service_id=self.service_id,
            infrastructure=InfrastructureMetrics(
                cpu_percent=round(base_cpu, 2),
                memory_percent=round(base_mem, 2),
                disk_io_mbps=round(base_disk, 2),
                network_egress_mbps=round(base_net_egress, 2),
                network_ingress_mbps=round(base_net_ingress, 2),
            ),
            application=ApplicationMetrics(
                service_id=self.service_id,
                endpoint=self.endpoint,
                requests_per_sec=round(base_rps, 2),
                latency_p50_ms=round(base_p50, 2),
                latency_p95_ms=round(base_p95, 2),
                latency_p99_ms=round(base_p99, 2),
                http_2xx_count=base_2xx,
                http_4xx_count=base_4xx,
                http_5xx_count=base_5xx,
            ),
            database=DatabaseMetrics(
                db_instance_id=self.db_instance_id,
                active_connections=base_db_active,
                connection_pool_utilization=round(base_db_pool, 2),
                query_latency_mean_ms=round(base_db_latency, 2),
                slow_queries_per_sec=round(base_db_slow_q, 2),
                row_lock_waits=base_db_locks,
            ),
            business=BusinessMetrics(
                order_volume=base_orders,
                revenue_usd=base_revenue,
                checkout_success_rate=round(base_checkout_success, 2),
                cart_abandonment_rate=round(base_cart_abandonment, 2),
            ),
            ground_truth_label=archetype,
            ground_truth_anomalous=is_anomalous,
            simulated_root_cause=root_cause_desc,
        )

    def generate_batch(
        self,
        num_snapshots: int = 100,
        archetype: AnomalyArchetype = AnomalyArchetype.NOMINAL,
        progress: float = 1.0,
    ) -> List[TelemetrySnapshot]:
        """Generate a consecutive list of snapshots under a steady archetype."""
        return [self.generate_snapshot(archetype=archetype, progress=progress) for _ in range(num_snapshots)]

    def generate_incident_scenario(
        self,
        archetype: AnomalyArchetype,
        total_ticks: int = 120,
        anomaly_start_tick: int = 40,
        anomaly_duration_ticks: int = 40,
    ) -> List[TelemetrySnapshot]:
        """Generate a realistic incident timeline: Nominal -> Ramp-up/Incident -> Recovery.

        - Ticks [0, anomaly_start_tick): Nominal baseline.
        - Ticks [anomaly_start_tick, anomaly_start_tick + anomaly_duration_ticks): Active anomaly.
        - Ticks [anomaly_start_tick + anomaly_duration_ticks, total_ticks): Recovery / Nominal.
        """
        snapshots: List[TelemetrySnapshot] = []
        anomaly_end_tick = anomaly_start_tick + anomaly_duration_ticks

        for tick in range(total_ticks):
            if tick < anomaly_start_tick:
                snap = self.generate_snapshot(archetype=AnomalyArchetype.NOMINAL)
            elif tick < anomaly_end_tick:
                progress = min(1.0, (tick - anomaly_start_tick + 1) / max(1, anomaly_duration_ticks // 2))
                snap = self.generate_snapshot(archetype=archetype, progress=progress)
            else:
                # Post-incident recovery
                recovery_progress = min(1.0, (tick - anomaly_end_tick + 1) / 10.0)
                if recovery_progress < 1.0:
                    snap = self.generate_snapshot(archetype=archetype, progress=1.0 - recovery_progress)
                else:
                    snap = self.generate_snapshot(archetype=AnomalyArchetype.NOMINAL)
            snapshots.append(snap)

        return snapshots

    def stream_telemetry(
        self,
        archetype: AnomalyArchetype = AnomalyArchetype.NOMINAL,
        max_snapshots: Optional[int] = None,
    ) -> Generator[TelemetrySnapshot, None, None]:
        """Yield snapshots indefinitely or up to max_snapshots for stream simulation."""
        generated = 0
        while max_snapshots is None or generated < max_snapshots:
            yield self.generate_snapshot(archetype=archetype)
            generated += 1

    @staticmethod
    def to_dataframe(snapshots: List[TelemetrySnapshot]) -> pd.DataFrame:
        """Convert a list of TelemetrySnapshot models into a flattened pandas DataFrame."""
        records: List[Dict] = []
        for s in snapshots:
            rec = {
                "timestamp": s.timestamp,
                "trace_id": s.trace_id,
                "service_id": s.service_id,
                # Infrastructure Tier
                "infra_cpu_percent": s.infrastructure.cpu_percent,
                "infra_memory_percent": s.infrastructure.memory_percent,
                "infra_disk_io_mbps": s.infrastructure.disk_io_mbps,
                "infra_network_egress_mbps": s.infrastructure.network_egress_mbps,
                "infra_network_ingress_mbps": s.infrastructure.network_ingress_mbps,
                # Application Tier
                "app_requests_per_sec": s.application.requests_per_sec,
                "app_latency_p50_ms": s.application.latency_p50_ms,
                "app_latency_p95_ms": s.application.latency_p95_ms,
                "app_latency_p99_ms": s.application.latency_p99_ms,
                "app_http_2xx_count": s.application.http_2xx_count,
                "app_http_4xx_count": s.application.http_4xx_count,
                "app_http_5xx_count": s.application.http_5xx_count,
                "app_error_rate": s.application.error_rate,
                # Database Tier
                "db_instance_id": s.database.db_instance_id,
                "db_active_connections": s.database.active_connections,
                "db_pool_utilization": s.database.connection_pool_utilization,
                "db_query_latency_ms": s.database.query_latency_mean_ms,
                "db_slow_queries_per_sec": s.database.slow_queries_per_sec,
                "db_row_lock_waits": s.database.row_lock_waits,
                # Business Tier
                "biz_order_volume": s.business.order_volume,
                "biz_revenue_usd": s.business.revenue_usd,
                "biz_checkout_success_rate": s.business.checkout_success_rate,
                "biz_cart_abandonment_rate": s.business.cart_abandonment_rate,
                # Evaluation Labels
                "ground_truth_label": s.ground_truth_label.value,
                "ground_truth_anomalous": s.ground_truth_anomalous,
                "simulated_root_cause": s.simulated_root_cause or "",
            }
            records.append(rec)
        return pd.DataFrame(records)
