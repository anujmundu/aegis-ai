"""Univariate Statistical Anomaly Detectors for AegisAI.

Implements:
1. RollingZScoreDetector: Standard 3-Sigma thresholding over a sliding window.
2. ModifiedZScoreDetector: Median Absolute Deviation (MAD) based detection,
   highly robust against extreme outlier distortion.
"""

from collections import deque
from typing import Deque, Literal

import numpy as np


class RollingZScoreDetector:
    """Sliding-window Z-score (3-Sigma) detector.

    Z = (x - mean) / std
    Flags anomaly when |Z| >= threshold (or directional threshold).
    """

    def __init__(
        self,
        window_size: int = 60,
        min_samples: int = 15,
        threshold: float = 3.0,
        direction: Literal["both", "upper", "lower"] = "both",
        epsilon: float = 1e-6,
    ) -> None:
        self.window_size = window_size
        self.min_samples = min_samples
        self.threshold = threshold
        self.direction = direction
        self.epsilon = epsilon
        self.window: Deque[float] = deque(maxlen=window_size)

    def reset(self) -> None:
        """Clear historical window buffer."""
        self.window.clear()

    def update_and_score(self, value: float) -> tuple[float, bool, float, float]:
        """Update window and score the new value.

        Returns:
            (z_score, is_anomaly, mean, std)
        """
        if len(self.window) < self.min_samples:
            self.window.append(value)
            return 0.0, False, value, 0.0

        mean = float(np.mean(self.window))
        std = float(np.std(self.window, ddof=1)) + self.epsilon
        z = (value - mean) / std

        is_anomaly = False
        if self.direction == "upper":
            is_anomaly = z >= self.threshold
        elif self.direction == "lower":
            is_anomaly = z <= -self.threshold
        else:
            is_anomaly = abs(z) >= self.threshold

        self.window.append(value)
        return z, is_anomaly, mean, std


class ModifiedZScoreDetector:
    """Median Absolute Deviation (MAD) based Modified Z-Score detector.

    MAD = median(|x_i - median(x)|)
    M_i = 0.6745 * (x_i - median(x)) / (MAD + epsilon)

    Unlike classical Z-score, MAD is not distorted by extreme outliers.
    """

    def __init__(
        self,
        window_size: int = 60,
        min_samples: int = 15,
        threshold: float = 3.5,
        direction: Literal["both", "upper", "lower"] = "both",
        epsilon: float = 1e-6,
    ) -> None:
        self.window_size = window_size
        self.min_samples = min_samples
        self.threshold = threshold
        self.direction = direction
        self.epsilon = epsilon
        self.window: Deque[float] = deque(maxlen=window_size)

    def reset(self) -> None:
        """Clear historical window buffer."""
        self.window.clear()

    def update_and_score(self, value: float) -> tuple[float, bool, float, float]:
        """Update window and score the new value.

        Returns:
            (mod_z_score, is_anomaly, median, mad)
        """
        if len(self.window) < self.min_samples:
            self.window.append(value)
            return 0.0, False, value, 0.0

        arr = np.array(self.window)
        median = float(np.median(arr))
        mad = float(np.median(np.abs(arr - median)))

        # 0.6745 is the consistency constant for the normal distribution
        mod_z = (0.6745 * (value - median)) / (mad + self.epsilon)

        is_anomaly = False
        if self.direction == "upper":
            is_anomaly = mod_z >= self.threshold
        elif self.direction == "lower":
            is_anomaly = mod_z <= -self.threshold
        else:
            is_anomaly = abs(mod_z) >= self.threshold

        self.window.append(value)
        return mod_z, is_anomaly, median, mad
