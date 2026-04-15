"""Exponentially Weighted Moving Average (EWMA) Control Chart Detector.

Provides high-sensitivity detection of persistent subtle mean shifts without
false alarms from single-sample transient spikes.

Mathematical formulation:
    z_t = lambda * x_t + (1 - lambda) * z_{t-1}
    sigma_{z_t} = sigma * sqrt((lambda / (2 - lambda)) * (1 - (1 - lambda)^(2t)))
    UCL_t = mu + L * sigma_{z_t}
    LCL_t = mu - L * sigma_{z_t}
"""

import math
from collections import deque
from typing import Deque, Literal

import numpy as np


class EWMADetector:
    """EWMA Control Chart detector with dynamic time-varying control limits."""

    def __init__(
        self,
        smoothing_lambda: float = 0.2,
        control_limit_multiplier: float = 3.0,
        warmup_samples: int = 15,
        baseline_learning_rate: float = 0.03,
        direction: Literal["both", "upper", "lower"] = "both",
        epsilon: float = 1e-6,
    ) -> None:
        if not (0.0 < smoothing_lambda <= 1.0):
            raise ValueError(f"smoothing_lambda must be in (0, 1], got {smoothing_lambda}")
        self.smoothing_lambda = smoothing_lambda
        self.control_limit_multiplier = control_limit_multiplier
        self.warmup_samples = warmup_samples
        self.baseline_learning_rate = baseline_learning_rate
        self.direction = direction
        self.epsilon = epsilon

        # State tracking
        self.warmup_buffer: Deque[float] = deque(maxlen=warmup_samples)
        self.is_warmed_up: bool = False
        self.step_t: int = 0
        self.z_t: float = 0.0
        self.baseline_mean: float = 0.0
        self.baseline_std: float = 0.0

    def reset(self) -> None:
        """Reset internal state, buffer, and counters."""
        self.warmup_buffer.clear()
        self.is_warmed_up = False
        self.step_t = 0
        self.z_t = 0.0
        self.baseline_mean = 0.0
        self.baseline_std = 0.0

    def update_and_score(
        self, value: float
    ) -> tuple[float, bool, float, float, float]:
        """Update EWMA with observation and evaluate control limits.

        Returns:
            (ewma_value, is_anomaly, baseline_mean, lcl, ucl)
        """
        # Warmup phase: collect initial observations to compute baseline mean and std
        if not self.is_warmed_up:
            self.warmup_buffer.append(value)
            if len(self.warmup_buffer) >= self.warmup_samples:
                self.baseline_mean = float(np.mean(self.warmup_buffer))
                self.baseline_std = float(np.std(self.warmup_buffer, ddof=1)) + self.epsilon
                self.z_t = self.baseline_mean
                self.is_warmed_up = True
            return value, False, value, value, value

        self.step_t += 1
        # Update smoothed EWMA statistic
        self.z_t = (self.smoothing_lambda * value) + ((1.0 - self.smoothing_lambda) * self.z_t)

        # Calculate time-varying EWMA standard deviation
        # term = (lambda / (2 - lambda)) * (1 - (1 - lambda)^(2t))
        factor = (self.smoothing_lambda / (2.0 - self.smoothing_lambda)) * (
            1.0 - math.pow(1.0 - self.smoothing_lambda, 2 * self.step_t)
        )
        sigma_zt = self.baseline_std * math.sqrt(max(0.0, factor))

        margin = self.control_limit_multiplier * sigma_zt
        ucl = self.baseline_mean + margin
        lcl = self.baseline_mean - margin

        is_anomaly = False
        if self.direction == "upper":
            is_anomaly = self.z_t > ucl
        elif self.direction == "lower":
            is_anomaly = self.z_t < lcl
        else:
            is_anomaly = (self.z_t > ucl) or (self.z_t < lcl)

        # Adapt baseline smoothly on healthy non-anomalous steps
        if not is_anomaly and self.baseline_learning_rate > 0.0:
            self.baseline_mean = (
                (1.0 - self.baseline_learning_rate) * self.baseline_mean
                + (self.baseline_learning_rate * value)
            )

        return self.z_t, is_anomaly, self.baseline_mean, lcl, ucl
