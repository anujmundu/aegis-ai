"""Supervised Multi-Class Incident Classifier for AegisAI.

Predicts which operational incident archetype is active:
0: NOMINAL
1: DB_CONNECTION_POOL_SATURATION
2: MEMORY_LEAK_GC_PAUSE
3: CASCADING_THIRD_PARTY_FAILURE
4: PAYMENT_GATEWAY_OUTAGE
5: BLACK_FRIDAY_TRAFFIC_BURST

Uses XGBoost or Scikit-learn HistGradientBoostingClassifier with full probability distribution.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import joblib
import numpy as np
from sklearn.preprocessing import LabelEncoder

from ml.features.feature_extractor import LABEL_TO_ARCHETYPE


class IncidentClassifier:
    """Supervised gradient-boosted incident classifier outputting probability distributions."""

    def __init__(
        self,
        model_type: str = "xgboost",
        n_estimators: int = 100,
        max_depth: int = 5,
        learning_rate: float = 0.1,
        feature_names: Optional[List[str]] = None,
        random_state: int = 42,
    ) -> None:
        self.model_type = model_type
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.feature_names = feature_names or []
        self.random_state = random_state
        self.label_encoder = LabelEncoder()
        self.is_fitted: bool = False
        self.model: Any = None

        self._init_model()

    def _init_model(self) -> None:
        """Initialize the underlying gradient boosting model."""
        if self.model_type == "xgboost":
            try:
                import xgboost as xgb
                self.model = xgb.XGBClassifier(
                    n_estimators=self.n_estimators,
                    max_depth=self.max_depth,
                    learning_rate=self.learning_rate,
                    random_state=self.random_state,
                    eval_metric="mlogloss",
                    verbosity=0,
                )
                return
            except ImportError:
                # Fallback gracefully to HistGradientBoostingClassifier
                self.model_type = "hist_gb"

        from sklearn.ensemble import HistGradientBoostingClassifier
        self.model = HistGradientBoostingClassifier(
            max_iter=self.n_estimators,
            max_depth=self.max_depth,
            learning_rate=self.learning_rate,
            random_state=self.random_state,
        )

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: Optional[List[str]] = None,
    ) -> "IncidentClassifier":
        """Train classifier on feature matrix and encoded integer labels."""
        if feature_names:
            self.feature_names = feature_names

        # Encode labels into contiguous integers [0..K-1] for XGBoost compliance
        y_contiguous = self.label_encoder.fit_transform(y)
        self.model.fit(X, y_contiguous)
        self.is_fitted = True
        return self

    def predict(
        self, x: np.ndarray
    ) -> Tuple[int, str, float, Dict[str, float]]:
        """Predict archetype class, label, confidence, and complete probability distribution.

        Returns:
            (predicted_class_id, archetype_name, confidence_score, probabilities_by_class)
        """
        if not self.is_fitted:
            raise RuntimeError("IncidentClassifier must be fitted before predict.")

        vec = x.reshape(1, -1) if x.ndim == 1 else x
        pred_encoded = int(self.model.predict(vec)[0])
        original_class_id = int(self.label_encoder.inverse_transform([pred_encoded])[0])
        probs = self.model.predict_proba(vec)[0]
        confidence = float(np.max(probs))
        archetype_name = LABEL_TO_ARCHETYPE.get(original_class_id, f"UNKNOWN_{original_class_id}")

        prob_dict: Dict[str, float] = {}
        for local_idx, p in enumerate(probs):
            orig_id = int(self.label_encoder.classes_[local_idx])
            name = LABEL_TO_ARCHETYPE.get(orig_id, f"CLASS_{orig_id}")
            prob_dict[name] = round(float(p), 4)

        return original_class_id, archetype_name, round(confidence, 4), prob_dict

    def get_feature_importances(self) -> Dict[str, float]:
        """Return feature importance scores if supported by underlying model."""
        if not self.is_fitted or not self.feature_names:
            return {}

        if hasattr(self.model, "feature_importances_"):
            importances = self.model.feature_importances_
            total = float(np.sum(importances)) + 1e-9
            res: Dict[str, float] = {}
            for name, imp in zip(self.feature_names, importances, strict=False):
                res[name] = round(float(imp / total), 4)
            # Sort descending
            return dict(sorted(res.items(), key=lambda kv: kv[1], reverse=True))

        return {}

    def save(self, filepath: Union[str, Path]) -> None:
        """Serialize model artifact to disk."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        artifact = {
            "model_type": self.model_type,
            "feature_names": self.feature_names,
            "label_encoder": self.label_encoder,
            "model": self.model,
        }
        joblib.dump(artifact, path)

    @classmethod
    def load(cls, filepath: Union[str, Path]) -> "IncidentClassifier":
        """Load serialized model artifact from disk."""
        artifact = joblib.load(filepath)
        clf = cls(model_type=artifact["model_type"], feature_names=artifact["feature_names"])
        clf.label_encoder = artifact["label_encoder"]
        clf.model = artifact["model"]
        clf.is_fitted = True
        return clf
