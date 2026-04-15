"""Statistical Anomaly Detection Engine for AegisAI.

Aggregates Univariate (Z-Score, Modified Z-Score), Time-Series (EWMA),
and Multivariate (Mahalanobis Distance, Pearson Correlation Drift)
detectors into a unified real-time operational inference engine.
"""

import uuid
from datetime import datetime, timezone
from typing import Dict, List

import numpy as np

from data.schemas.events import AnomalySignal, IncidentSeverity, TelemetrySnapshot
from ml.models.statistical.ewma import EWMADetector
from ml.models.statistical.multivariate import (
    MahalanobisDetector,
    PearsonCorrelationDriftDetector,
)
from ml.models.statistical.univariate import ModifiedZScoreDetector, RollingZScoreDetector

MULTIVARIATE_FEATURES = [
    "cpu_percent",
    "memory_percent",
    "disk_io_mbps",
    "network_egress_mbps",
    "latency_p50_ms",
    "latency_p95_ms",
    "latency_p99_ms",
    "connection_pool_utilization",
    "query_latency_mean_ms",
    "requests_per_sec",
    "checkout_success_rate",
]


class StatisticalAnomalyEngine:
    """Enterprise statistical anomaly engine executing multi-tier detectors in <15ms."""

    def __init__(
        self,
        service_id: str = "checkout-service",
        window_size: int = 60,
        z_threshold: float = 3.0,
        mad_threshold: float = 3.5,
    ) -> None:
        self.service_id = service_id
        self.window_size = window_size
        self.z_threshold = z_threshold
        self.mad_threshold = mad_threshold

        # 1. Univariate Detectors (Rolling Z-Score & MAD)
        self.z_detectors: Dict[str, RollingZScoreDetector] = {
            "infra_cpu_percent": RollingZScoreDetector(window_size, threshold=z_threshold, direction="upper"),
            "infra_memory_percent": RollingZScoreDetector(window_size, threshold=z_threshold, direction="upper"),
            "app_latency_p95_ms": RollingZScoreDetector(window_size, threshold=z_threshold, direction="upper"),
            "app_latency_p99_ms": RollingZScoreDetector(window_size, threshold=z_threshold, direction="upper"),
            "app_error_rate": RollingZScoreDetector(window_size, threshold=z_threshold, direction="upper"),
            "db_pool_utilization": RollingZScoreDetector(window_size, threshold=z_threshold, direction="upper"),
            "db_query_latency_ms": RollingZScoreDetector(window_size, threshold=z_threshold, direction="upper"),
            "biz_checkout_success_rate": RollingZScoreDetector(window_size, threshold=z_threshold, direction="lower"),
        }

        self.mad_detectors: Dict[str, ModifiedZScoreDetector] = {
            "app_latency_p99_ms": ModifiedZScoreDetector(window_size, threshold=mad_threshold, direction="upper"),
            "db_query_latency_ms": ModifiedZScoreDetector(window_size, threshold=mad_threshold, direction="upper"),
            "biz_checkout_success_rate": ModifiedZScoreDetector(window_size, threshold=mad_threshold, direction="lower"),
        }

        # 2. Time-Series EWMA Detectors (Subtle Drift Detection)
        self.ewma_detectors: Dict[str, EWMADetector] = {
            "infra_memory_percent": EWMADetector(smoothing_lambda=0.15, control_limit_multiplier=3.0, direction="upper"),
            "app_latency_p95_ms": EWMADetector(smoothing_lambda=0.20, control_limit_multiplier=3.0, direction="upper"),
            "db_pool_utilization": EWMADetector(smoothing_lambda=0.20, control_limit_multiplier=3.0, direction="upper"),
            "biz_checkout_success_rate": EWMADetector(smoothing_lambda=0.25, control_limit_multiplier=3.0, direction="lower"),
        }

        # 3. Multivariate Covariance Detector (calibrated to enterprise multi-metric incidents)
        self.mahalanobis = MahalanobisDetector(feature_names=MULTIVARIATE_FEATURES, significance_alpha=1e-5)

        # 4. Cross-Tier Pearson Correlation Drift Detectors (Coupled metric relationships)
        self.correlation_detectors: List[PearsonCorrelationDriftDetector] = [
            # Traffic vs Business Orders (Strongly coupled; collapses during payment outage)
            PearsonCorrelationDriftDetector(
                signal_x_name="app_requests_per_sec",
                signal_y_name="biz_order_volume",
                expected_correlation=0.90,
                drift_threshold=0.55,
                window_size=30,
            ),
            # Traffic vs Network Egress (Strongly coupled; collapses during thread stall)
            PearsonCorrelationDriftDetector(
                signal_x_name="app_requests_per_sec",
                signal_y_name="infra_network_egress_mbps",
                expected_correlation=0.85,
                drift_threshold=0.55,
                window_size=30,
            ),
        ]

    def _extract_metric_values(self, s: TelemetrySnapshot) -> Dict[str, float]:
        """Extract a flat metric map from a TelemetrySnapshot."""
        return {
            "infra_cpu_percent": s.infrastructure.cpu_percent,
            "infra_memory_percent": s.infrastructure.memory_percent,
            "infra_disk_io_mbps": s.infrastructure.disk_io_mbps,
            "infra_network_egress_mbps": s.infrastructure.network_egress_mbps,
            "app_requests_per_sec": s.application.requests_per_sec,
            "app_latency_p50_ms": s.application.latency_p50_ms,
            "app_latency_p95_ms": s.application.latency_p95_ms,
            "app_latency_p99_ms": s.application.latency_p99_ms,
            "app_error_rate": s.application.error_rate,
            "db_pool_utilization": s.database.connection_pool_utilization,
            "db_query_latency_ms": s.database.query_latency_mean_ms,
            "biz_order_volume": float(s.business.order_volume),
            "biz_checkout_success_rate": s.business.checkout_success_rate,
        }

    def _extract_multivariate_vector(self, s: TelemetrySnapshot) -> np.ndarray:
        """Extract standardized multivariate feature vector."""
        return np.array([
            s.infrastructure.cpu_percent,
            s.infrastructure.memory_percent,
            s.infrastructure.disk_io_mbps,
            s.infrastructure.network_egress_mbps,
            s.application.latency_p50_ms,
            s.application.latency_p95_ms,
            s.application.latency_p99_ms,
            s.database.connection_pool_utilization,
            s.database.query_latency_mean_ms,
            s.application.requests_per_sec,
            s.business.checkout_success_rate,
        ], dtype=float)

    def fit_baseline(self, baseline_snapshots: List[TelemetrySnapshot]) -> None:
        """Calibrate detectors using a sequence of nominal baseline snapshots."""
        if not baseline_snapshots:
            return

        # Fit Multivariate Covariance Matrix
        matrix = np.array([self._extract_multivariate_vector(s) for s in baseline_snapshots])
        self.mahalanobis.fit(matrix)

        # Warm up Univariate and EWMA Detectors
        for s in baseline_snapshots:
            metrics = self._extract_metric_values(s)
            for m_name, det in self.z_detectors.items():
                if m_name in metrics:
                    det.update_and_score(metrics[m_name])
            for m_name, det in self.mad_detectors.items():
                if m_name in metrics:
                    det.update_and_score(metrics[m_name])
            for m_name, det in self.ewma_detectors.items():
                if m_name in metrics:
                    det.update_and_score(metrics[m_name])
        # Fit Correlation Detectors from the calibration series
        all_metrics = [self._extract_metric_values(s) for s in baseline_snapshots]
        for corr_det in self.correlation_detectors:
            arr_x = np.array([m.get(corr_det.signal_x_name, 0.0) for m in all_metrics])
            arr_y = np.array([m.get(corr_det.signal_y_name, 0.0) for m in all_metrics])
            corr_det.fit(arr_x, arr_y)

    def _determine_severity(self, abs_sigma: float) -> IncidentSeverity:
        """Map deviation sigma to operational incident severity."""
        if abs_sigma >= 5.0:
            return IncidentSeverity.CRITICAL
        elif abs_sigma >= 3.5:
            return IncidentSeverity.HIGH
        elif abs_sigma >= 2.5:
            return IncidentSeverity.MEDIUM
        return IncidentSeverity.LOW

    def analyze_snapshot(self, snapshot: TelemetrySnapshot) -> List[AnomalySignal]:
        """Analyze a single operational telemetry snapshot and emit anomaly signals."""
        signals: List[AnomalySignal] = []
        metrics = self._extract_metric_values(snapshot)
        ts = snapshot.timestamp or datetime.now(timezone.utc)

        # 1. Evaluate Rolling Z-Score Detectors
        for m_name, det in self.z_detectors.items():
            if m_name in metrics:
                val = metrics[m_name]
                z, is_anom, mean, std = det.update_and_score(val)
                if is_anom:
                    signals.append(
                        AnomalySignal(
                            signal_id=f"sig-{uuid.uuid4().hex[:8]}",
                            service_id=snapshot.service_id,
                            metric_name=m_name,
                            detector_type="z_score",
                            observed_value=round(val, 2),
                            baseline_value=round(mean, 2),
                            deviation_sigma=round(z, 2),
                            severity=self._determine_severity(abs(z)),
                            is_anomaly=True,
                            timestamp=ts,
                            metadata={"window_std": str(round(std, 2))},
                        )
                    )

        # 2. Evaluate Modified Z-Score (MAD) Detectors
        for m_name, det in self.mad_detectors.items():
            if m_name in metrics:
                val = metrics[m_name]
                mod_z, is_anom, median, mad = det.update_and_score(val)
                if is_anom:
                    signals.append(
                        AnomalySignal(
                            signal_id=f"sig-{uuid.uuid4().hex[:8]}",
                            service_id=snapshot.service_id,
                            metric_name=m_name,
                            detector_type="modified_z_score",
                            observed_value=round(val, 2),
                            baseline_value=round(median, 2),
                            deviation_sigma=round(mod_z, 2),
                            severity=self._determine_severity(abs(mod_z)),
                            is_anomaly=True,
                            timestamp=ts,
                            metadata={"window_mad": str(round(mad, 2))},
                        )
                    )

        # 3. Evaluate EWMA Detectors (Time-series drift)
        for m_name, det in self.ewma_detectors.items():
            if m_name in metrics:
                val = metrics[m_name]
                ewma_val, is_anom, base_mean, lcl, ucl = det.update_and_score(val)
                if is_anom:
                    diff = ewma_val - base_mean
                    signals.append(
                        AnomalySignal(
                            signal_id=f"sig-{uuid.uuid4().hex[:8]}",
                            service_id=snapshot.service_id,
                            metric_name=m_name,
                            detector_type="ewma",
                            observed_value=round(val, 2),
                            baseline_value=round(base_mean, 2),
                            deviation_sigma=round(diff / max(1.0, abs(base_mean) * 0.1), 2),
                            severity=self._determine_severity(abs(diff)),
                            is_anomaly=True,
                            timestamp=ts,
                            metadata={"ucl": str(round(ucl, 2)), "lcl": str(round(lcl, 2))},
                        )
                    )

        # 4. Evaluate Multivariate Mahalanobis Detector
        if self.mahalanobis.is_fitted:
            vec = self._extract_multivariate_vector(snapshot)
            dist, p_val, is_anom, attributions = self.mahalanobis.score(vec)
            if is_anom and dist >= (self.mahalanobis.critical_distance * 1.5):
                top_feature = max(attributions.items(), key=lambda kv: kv[1])[0] if attributions else "unknown"
                signals.append(
                    AnomalySignal(
                        signal_id=f"sig-{uuid.uuid4().hex[:8]}",
                        service_id=snapshot.service_id,
                        metric_name="multivariate_system_state",
                        detector_type="mahalanobis",
                        observed_value=round(dist, 2),
                        baseline_value=round(self.mahalanobis.critical_distance, 2),
                        deviation_sigma=round(dist - self.mahalanobis.critical_distance, 2),
                        severity=IncidentSeverity.CRITICAL if dist > self.mahalanobis.critical_distance * 1.5 else IncidentSeverity.HIGH,
                        is_anomaly=True,
                        is_primary_driver=True,
                        timestamp=ts,
                        metadata={
                            "p_value": f"{p_val:.2e}",
                            "top_contributor": top_feature,
                            "top_attribution_pct": str(attributions.get(top_feature, 0.0)),
                        },
                    )
                )

        # 5. Evaluate Pearson Correlation Drift Detectors
        for corr_det in self.correlation_detectors:
            val_x = metrics.get(corr_det.signal_x_name, 0.0)
            val_y = metrics.get(corr_det.signal_y_name, 0.0)
            curr_r, drift, is_anom = corr_det.update_and_score(val_x, val_y)
            if is_anom:
                signals.append(
                    AnomalySignal(
                        signal_id=f"sig-{uuid.uuid4().hex[:8]}",
                        service_id=snapshot.service_id,
                        metric_name=f"correlation_{corr_det.signal_x_name}_vs_{corr_det.signal_y_name}",
                        detector_type="correlation_drift",
                        observed_value=round(curr_r, 2),
                        baseline_value=round(corr_det.expected_correlation, 2),
                        deviation_sigma=round(drift * 5.0, 2),
                        severity=IncidentSeverity.HIGH if drift > 0.8 else IncidentSeverity.MEDIUM,
                        is_anomaly=True,
                        timestamp=ts,
                        metadata={"drift_delta": str(round(drift, 2))},
                    )
                )

        # 6. Designate Primary Driver
        if signals:
            # If no signal was marked primary driver yet, pick the one with max deviation_sigma
            has_primary = any(s.is_primary_driver for s in signals)
            if not has_primary:
                max_sig = max(signals, key=lambda s: abs(s.deviation_sigma))
                max_sig.is_primary_driver = True

        return signals
