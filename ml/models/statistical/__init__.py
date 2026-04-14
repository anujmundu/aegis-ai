"""Statistical Anomaly Detection package for AegisAI."""

from ml.models.statistical.engine import StatisticalAnomalyEngine
from ml.models.statistical.ewma import EWMADetector
from ml.models.statistical.multivariate import (
    MahalanobisDetector,
    PearsonCorrelationDriftDetector,
)
from ml.models.statistical.univariate import ModifiedZScoreDetector, RollingZScoreDetector

__all__ = [
    "EWMADetector",
    "MahalanobisDetector",
    "ModifiedZScoreDetector",
    "PearsonCorrelationDriftDetector",
    "RollingZScoreDetector",
    "StatisticalAnomalyEngine",
]
