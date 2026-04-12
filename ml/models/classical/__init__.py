"""Classical ML models package for AegisAI."""

from ml.models.classical.incident_classifier import IncidentClassifier
from ml.models.classical.isolation_forest import IsolationForestDetector

__all__ = [
    "IncidentClassifier",
    "IsolationForestDetector",
]
