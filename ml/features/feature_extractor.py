"""Operational Feature Engineering Pipeline for Multi-Tier Telemetry.

Extracts:
1. Instantaneous cross-tier ratios & spreads (e.g., latency p99-p50 spread, orders/RPS ratio).
2. Rolling temporal dynamics (rolling means, rolling std, first-difference rates of change).
3. Supervised archetype label encoding.
Supports both batch DataFrame training and online single-snapshot streaming inference.
"""

from collections import deque
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple, Union

import joblib
import numpy as np
import pandas as pd

from data.schemas.events import AnomalyArchetype, TelemetrySnapshot

ARCHETYPE_LABEL_MAP: Dict[str, int] = {
    AnomalyArchetype.NOMINAL.value: 0,
    AnomalyArchetype.DB_CONNECTION_POOL_SATURATION.value: 1,
    AnomalyArchetype.MEMORY_LEAK_GC_PAUSE.value: 2,
    AnomalyArchetype.CASCADING_THIRD_PARTY_FAILURE.value: 3,
    AnomalyArchetype.PAYMENT_GATEWAY_OUTAGE.value: 4,
    AnomalyArchetype.BLACK_FRIDAY_TRAFFIC_BURST.value: 5,
}

LABEL_TO_ARCHETYPE: Dict[int, str] = {v: k for k, v in ARCHETYPE_LABEL_MAP.items()}


BASE_NUMERIC_COLUMNS = [
    "infra_cpu_percent",
    "infra_memory_percent",
    "infra_disk_io_mbps",
    "infra_network_egress_mbps",
    "infra_network_ingress_mbps",
    "app_requests_per_sec",
    "app_latency_p50_ms",
    "app_latency_p95_ms",
    "app_latency_p99_ms",
    "app_http_2xx_count",
    "app_http_4xx_count",
    "app_http_5xx_count",
    "app_error_rate",
    "db_active_connections",
    "db_pool_utilization",
    "db_query_latency_ms",
    "db_slow_queries_per_sec",
    "db_row_lock_waits",
    "biz_order_volume",
    "biz_revenue_usd",
    "biz_checkout_success_rate",
    "biz_cart_abandonment_rate",
]


class TelemetryFeatureExtractor:
    """Production feature engineering pipeline transforming snapshots into ML feature vectors."""

    def __init__(self, window_size: int = 10, epsilon: float = 1e-6) -> None:
        self.window_size = window_size
        self.epsilon = epsilon
        self.is_fitted: bool = False
        self.feature_names: List[str] = []
        self.means_: Optional[np.ndarray] = None
        self.stds_: Optional[np.ndarray] = None

        # Online streaming buffer for single-snapshot inference
        self._streaming_history: Deque[Dict[str, float]] = deque(maxlen=window_size)

    def reset_online_buffer(self) -> None:
        """Clear streaming window buffer."""
        self._streaming_history.clear()

    def _engineer_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute engineered metrics, ratios, and rolling aggregates over a DataFrame."""
        out = pd.DataFrame(index=df.index)

        # 1. Base Metrics
        for col in BASE_NUMERIC_COLUMNS:
            if col in df.columns:
                out[col] = df[col].astype(float)
            else:
                out[col] = 0.0

        # 2. Cross-Tier Spreads & Ratios
        out["app_latency_spread_p99_p50"] = out["app_latency_p99_ms"] - out["app_latency_p50_ms"]
        out["app_latency_ratio_p99_p50"] = out["app_latency_p99_ms"] / (out["app_latency_p50_ms"] + self.epsilon)
        out["biz_orders_per_request"] = out["biz_order_volume"] / (out["app_requests_per_sec"] + self.epsilon)
        out["db_query_to_app_latency_ratio"] = out["db_query_latency_ms"] / (out["app_latency_p50_ms"] + self.epsilon)

        # 3. Rolling Temporal Features (Mean, Std, and Delta Rate of Change)
        rolling_targets = [
            "infra_cpu_percent",
            "infra_memory_percent",
            "app_latency_p95_ms",
            "db_pool_utilization",
            "biz_checkout_success_rate",
        ]

        for col in rolling_targets:
            # Rolling Mean
            out[f"{col}_roll_mean"] = out[col].rolling(window=self.window_size, min_periods=1).mean()
            # Rolling Standard Deviation
            out[f"{col}_roll_std"] = (
                out[col].rolling(window=self.window_size, min_periods=1).std().fillna(0.0)
            )
            # First Difference (Velocity / Rate of Change)
            out[f"{col}_delta"] = out[col].diff().fillna(0.0)

        return out

    def fit(self, df: pd.DataFrame) -> "TelemetryFeatureExtractor":
        """Compute mean and variance for standard normalization."""
        feat_df = self._engineer_dataframe(df)
        self.feature_names = list(feat_df.columns)
        self.means_ = feat_df.values.mean(axis=0)
        self.stds_ = feat_df.values.std(axis=0) + self.epsilon
        self.is_fitted = True
        return self

    def transform(self, df: pd.DataFrame) -> np.ndarray:
        """Transform DataFrame into normalized feature matrix."""
        if not self.is_fitted or self.means_ is None or self.stds_ is None:
            raise RuntimeError("TelemetryFeatureExtractor must be fitted before transform.")

        feat_df = self._engineer_dataframe(df)
        # Standardize features: (x - mu) / sigma
        scaled = (feat_df.values - self.means_) / self.stds_
        return np.nan_to_num(scaled, nan=0.0, posinf=5.0, neginf=-5.0)

    def fit_transform(
        self, df: pd.DataFrame
    ) -> Tuple[np.ndarray, np.ndarray, List[str]]:
        """Fit extractor and transform batch, returning (X, y, feature_names)."""
        self.fit(df)
        X = self.transform(df)

        # Encode labels if ground_truth_label column is present
        if "ground_truth_label" in df.columns:
            y = np.array(
                [ARCHETYPE_LABEL_MAP.get(str(lbl), 0) for lbl in df["ground_truth_label"]],
                dtype=int,
            )
        else:
            y = np.zeros(len(df), dtype=int)

        return X, y, self.feature_names

    def transform_snapshot(self, snapshot: TelemetrySnapshot) -> np.ndarray:
        """Transform a single snapshot in real-time streaming inference.

        Maintains an internal deque history to compute rolling features.
        """
        if not self.is_fitted or self.means_ is None or self.stds_ is None:
            raise RuntimeError("TelemetryFeatureExtractor must be fitted before streaming transform.")

        # Extract current raw metrics
        raw = {
            "infra_cpu_percent": snapshot.infrastructure.cpu_percent,
            "infra_memory_percent": snapshot.infrastructure.memory_percent,
            "infra_disk_io_mbps": snapshot.infrastructure.disk_io_mbps,
            "infra_network_egress_mbps": snapshot.infrastructure.network_egress_mbps,
            "infra_network_ingress_mbps": snapshot.infrastructure.network_ingress_mbps,
            "app_requests_per_sec": snapshot.application.requests_per_sec,
            "app_latency_p50_ms": snapshot.application.latency_p50_ms,
            "app_latency_p95_ms": snapshot.application.latency_p95_ms,
            "app_latency_p99_ms": snapshot.application.latency_p99_ms,
            "app_http_2xx_count": float(snapshot.application.http_2xx_count),
            "app_http_4xx_count": float(snapshot.application.http_4xx_count),
            "app_http_5xx_count": float(snapshot.application.http_5xx_count),
            "app_error_rate": snapshot.application.error_rate,
            "db_active_connections": float(snapshot.database.active_connections),
            "db_pool_utilization": snapshot.database.connection_pool_utilization,
            "db_query_latency_ms": snapshot.database.query_latency_mean_ms,
            "db_slow_queries_per_sec": snapshot.database.slow_queries_per_sec,
            "db_row_lock_waits": float(snapshot.database.row_lock_waits),
            "biz_order_volume": float(snapshot.business.order_volume),
            "biz_revenue_usd": snapshot.business.revenue_usd,
            "biz_checkout_success_rate": snapshot.business.checkout_success_rate,
            "biz_cart_abandonment_rate": snapshot.business.cart_abandonment_rate,
        }

        self._streaming_history.append(raw)
        recent_df = pd.DataFrame(list(self._streaming_history))
        feat_df = self._engineer_dataframe(recent_df)

        # Take the most recent row
        latest_vec = feat_df.iloc[-1].values
        scaled = (latest_vec - self.means_) / self.stds_
        return np.nan_to_num(scaled, nan=0.0, posinf=5.0, neginf=-5.0).reshape(1, -1)

    def save(self, filepath: Union[str, Path]) -> None:
        """Serialize feature extractor state to disk."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @classmethod
    def load(cls, filepath: Union[str, Path]) -> "TelemetryFeatureExtractor":
        """Load serialized feature extractor from disk."""
        return joblib.load(filepath)
