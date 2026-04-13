"""Classical Unsupervised Anomaly Detection using Isolation Forest.

Partitions high-dimensional operational telemetry space with orthogonal splits
to isolate structural outliers with minimal tree path lengths.
"""

from pathlib import Path
from typing import Tuple, Union

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest


class IsolationForestDetector:
    """Production Isolation Forest detector with normalized anomaly scoring."""

    def __init__(
        self,
        contamination: float = 0.05,
        n_estimators: int = 100,
        max_samples: Union[str, float, int] = "auto",
        random_state: int = 42,
    ) -> None:
        self.contamination = contamination
        self.n_estimators = n_estimators
        self.max_samples = max_samples
        self.random_state = random_state
        self.is_fitted: bool = False

        self.model = IsolationForest(
            contamination=contamination,
            n_estimators=n_estimators,
            max_samples=max_samples,
            random_state=random_state,
            n_jobs=-1,
        )

    def fit(self, X: np.ndarray) -> "IsolationForestDetector":
        """Fit Isolation Forest on nominal or mixed operational telemetry."""
        self.model.fit(X)
        self.is_fitted = True
        return self

    def score(self, x: np.ndarray) -> Tuple[float, bool]:
        """Score an observation vector.

        Returns:
            (normalized_anomaly_score, is_anomaly)
            where score is bounded in [0.0, 1.0] (higher = more anomalous).
        """
        if not self.is_fitted:
            raise RuntimeError("IsolationForestDetector must be fitted before scoring.")

        vec = x.reshape(1, -1) if x.ndim == 1 else x
        # decision_function yields negative for outliers, positive for inliers
        raw_decision = float(self.model.decision_function(vec)[0])
        pred = int(self.model.predict(vec)[0])  # -1 for anomaly, 1 for inlier

        # Map decision function to [0, 1] range: centered at 0.5
        norm_score = float(np.clip(0.5 - (raw_decision / 1.0), 0.0, 1.0))
        is_anomaly = pred == -1

        return round(norm_score, 4), is_anomaly

    def save(self, filepath: Union[str, Path]) -> None:
        """Serialize model artifact to disk."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.model, path)

    @classmethod
    def load(cls, filepath: Union[str, Path]) -> "IsolationForestDetector":
        """Load serialized model artifact from disk."""
        det = cls()
        det.model = joblib.load(filepath)
        det.is_fitted = True
        return det
