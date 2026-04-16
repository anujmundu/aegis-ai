"""Multivariate Statistical Anomaly Detectors for AegisAI.

Implements:
1. MahalanobisDetector: Multi-metric covariance-aware distance with feature attribution
   and Chi-Square significance testing.
2. PearsonCorrelationDriftDetector: Tracks relational coupling and operational decoupling
   between paired metrics across architectural tiers.
"""

from collections import deque
from typing import Deque, Dict, List, Tuple

import numpy as np
from scipy import stats


class MahalanobisDetector:
    """Covariance-aware multivariate anomaly detector with feature attribution.

    Mahalanobis Distance: D_M(x) = sqrt((x - mu)^T * Sigma^{-1} * (x - mu))
    Under Gaussian assumption, D_M^2 follows a Chi-Square distribution with d degrees of freedom.
    """

    def __init__(
        self,
        feature_names: List[str],
        significance_alpha: float = 0.001,
        regularization: float = 1e-4,
    ) -> None:
        self.feature_names = feature_names
        self.d = len(feature_names)
        self.significance_alpha = significance_alpha
        self.regularization = regularization

        # Critical value from chi-square distribution for the given alpha
        self.critical_value_sq = float(stats.chi2.ppf(1.0 - significance_alpha, df=self.d))
        self.critical_distance = float(np.sqrt(self.critical_value_sq))

        self.is_fitted: bool = False
        self.mean_vector: np.ndarray = np.zeros(self.d)
        self.inv_covariance: np.ndarray = np.eye(self.d)

    def fit(self, baseline_matrix: np.ndarray) -> "MahalanobisDetector":
        """Fit baseline mean vector and inverted covariance matrix.

        Args:
            baseline_matrix: Array of shape (N, d) containing nominal observations.
        """
        if baseline_matrix.shape[1] != self.d:
            raise ValueError(
                f"Expected matrix with {self.d} columns, got {baseline_matrix.shape[1]}"
            )

        self.mean_vector = np.mean(baseline_matrix, axis=0)
        cov = np.cov(baseline_matrix, rowvar=False)

        # Apply Tikhonov / Ridge regularization to guarantee invertibility
        cov_reg = cov + (np.eye(self.d) * self.regularization)
        try:
            self.inv_covariance = np.linalg.inv(cov_reg)
        except np.linalg.LinAlgError:
            self.inv_covariance = np.linalg.pinv(cov_reg)

        self.is_fitted = True
        return self

    def score(
        self, feature_vector: np.ndarray
    ) -> Tuple[float, float, bool, Dict[str, float]]:
        """Score a multivariate observation vector.

        Returns:
            (distance, p_value, is_anomaly, feature_attributions)
        """
        if not self.is_fitted:
            raise RuntimeError("MahalanobisDetector must be fitted before scoring.")

        diff = feature_vector - self.mean_vector
        # Mahalanobis distance squared: diff^T * Sigma^{-1} * diff
        intermediate = np.dot(diff, self.inv_covariance)
        dist_sq = float(np.dot(intermediate, diff))
        dist_sq = max(0.0, dist_sq)
        distance = float(np.sqrt(dist_sq))

        # p-value from survival function (1 - CDF)
        p_val = float(stats.chi2.sf(dist_sq, df=self.d))
        is_anomaly = dist_sq >= self.critical_value_sq

        # Feature attribution: contribution of each feature to the total distance squared
        # c_i = diff_i * (Sigma^{-1} * diff)_i
        contributions = diff * intermediate
        total_contrib = np.sum(np.abs(contributions)) + 1e-9
        attribution: Dict[str, float] = {}
        for name, contrib in zip(self.feature_names, contributions, strict=False):
            attribution[name] = round(float(np.abs(contrib) / total_contrib), 4)

        return distance, p_val, is_anomaly, attribution


class PearsonCorrelationDriftDetector:
    """Sliding-window Pearson correlation drift detector for paired metrics.

    Detects operational decoupling (e.g. traffic surges but orders collapse,
    or DB connection pool saturates but CPU drops due to I/O wait).
    """

    def __init__(
        self,
        signal_x_name: str,
        signal_y_name: str,
        expected_correlation: float,
        drift_threshold: float = 0.5,
        window_size: int = 30,
        min_samples: int = 15,
    ) -> None:
        self.signal_x_name = signal_x_name
        self.signal_y_name = signal_y_name
        self.expected_correlation = expected_correlation
        self.drift_threshold = drift_threshold
        self.window_size = window_size
        self.min_samples = min_samples

        self.buffer_x: Deque[float] = deque(maxlen=window_size)
        self.buffer_y: Deque[float] = deque(maxlen=window_size)

    def reset(self) -> None:
        """Reset historical buffers."""
        self.buffer_x.clear()
        self.buffer_y.clear()

    def fit(self, arr_x: np.ndarray, arr_y: np.ndarray) -> "PearsonCorrelationDriftDetector":
        """Fit expected baseline correlation and initialize buffer from calibration observations."""
        self.reset()
        if len(arr_x) >= self.min_samples and np.std(arr_x) > 1e-6 and np.std(arr_y) > 1e-6:
            r, _ = stats.pearsonr(arr_x, arr_y)
            if not np.isnan(r):
                self.expected_correlation = float(r)

        for x, y in zip(arr_x[-self.window_size:], arr_y[-self.window_size:], strict=False):
            self.buffer_x.append(float(x))
            self.buffer_y.append(float(y))

        return self

    def update_and_score(
        self, val_x: float, val_y: float
    ) -> Tuple[float, float, bool]:
        """Update window with paired observation and compute correlation drift.

        Returns:
            (current_correlation, drift_delta, is_anomaly)
        """
        self.buffer_x.append(val_x)
        self.buffer_y.append(val_y)

        if len(self.buffer_x) < self.min_samples:
            return self.expected_correlation, 0.0, False

        arr_x = np.array(self.buffer_x)
        arr_y = np.array(self.buffer_y)

        std_x = np.std(arr_x)
        std_y = np.std(arr_y)

        if std_x < 1e-6 or std_y < 1e-6:
            # Flatline in one variable means correlation is undefined
            return self.expected_correlation, 0.0, False

        r, _ = stats.pearsonr(arr_x, arr_y)
        if np.isnan(r):
            r = self.expected_correlation

        drift = float(abs(r - self.expected_correlation))
        is_anomaly = drift >= self.drift_threshold

        return float(r), drift, is_anomaly
