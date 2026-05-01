"""Comprehensive Unit Tests for Phase 3 ML Models.

Covers:
1. TelemetryFeatureExtractor (Batch & online streaming transformation)
2. ReconstructionAutoencoder (Analytical He/Adam network, reconstruction scoring, attribution)
3. IsolationForestDetector (Unsupervised partitioning, score normalization)
4. IncidentClassifier (Supervised gradient boosted multi-class archetype classification)
"""

from pathlib import Path

import numpy as np
import pytest

from data.schemas.events import AnomalyArchetype
from data.synthetic.telemetry_generator import MultiTierTelemetryGenerator
from ml.features.feature_extractor import ARCHETYPE_LABEL_MAP, TelemetryFeatureExtractor
from ml.models.classical.incident_classifier import IncidentClassifier
from ml.models.classical.isolation_forest import IsolationForestDetector
from ml.models.deep.autoencoder import ReconstructionAutoencoder

# =============================================================================
# 1. TelemetryFeatureExtractor Tests
# =============================================================================

def test_feature_extractor_batch_and_streaming():
    """Verify feature extractor computes correct features in batch and streaming mode."""
    generator = MultiTierTelemetryGenerator(seed=42)
    snaps = generator.generate_batch(num_snapshots=30, archetype=AnomalyArchetype.NOMINAL)
    df = MultiTierTelemetryGenerator.to_dataframe(snaps)

    extractor = TelemetryFeatureExtractor(window_size=5)
    X, y, feature_names = extractor.fit_transform(df)

    assert X.shape[0] == 30
    assert X.shape[1] > 25
    assert len(feature_names) == X.shape[1]
    assert np.isnan(X).sum() == 0

    # Online streaming transform
    extractor.reset_online_buffer()
    stream_vec = extractor.transform_snapshot(snaps[-1])
    assert stream_vec.shape == (1, X.shape[1])
    assert np.isnan(stream_vec).sum() == 0


# =============================================================================
# 2. ReconstructionAutoencoder Tests
# =============================================================================

def test_autoencoder_training_and_attribution(tmp_path: Path):
    """Verify deep autoencoder learns nominal manifold and attributes outliers."""
    rng = np.random.default_rng(42)
    N, d = 80, 15
    X_nominal = rng.normal(0.0, 1.0, (N, d))

    feature_names = [f"signal_{i}" for i in range(d)]
    ae = ReconstructionAutoencoder(
        input_dim=d,
        hidden_dim=12,
        latent_dim=4,
        threshold_sigmas=2.5,
        feature_names=feature_names,
        seed=42,
    )
    ae.fit(X_nominal, epochs=40, batch_size=16, lr=0.01)
    assert ae.is_fitted is True
    assert ae.threshold > 0.0

    # Test nominal point
    nom_vec = rng.normal(0.0, 0.8, (1, d))
    mse_nom, is_nom_anom, _, _ = ae.score(nom_vec)
    assert mse_nom < ae.threshold * 2.0

    # Test severe outlier in signal_3
    outlier = np.copy(nom_vec)
    outlier[0, 3] = 15.0  # Massive spike in signal 3
    mse_anom, is_anom, z_dev, attribution = ae.score(outlier)

    assert is_anom is True
    assert mse_anom > ae.threshold
    assert z_dev > 5.0
    # Top contributor should be signal_3
    top_feat = max(attribution.items(), key=lambda kv: kv[1])[0]
    assert top_feat == "signal_3"

    # Test save and load weights
    weights_path = tmp_path / "test_ae_weights.json"
    ae.save_weights(weights_path)
    loaded_ae = ReconstructionAutoencoder.load_weights(weights_path)
    assert loaded_ae.is_fitted is True
    assert loaded_ae.threshold == pytest.approx(ae.threshold, rel=1e-5)


# =============================================================================
# 3. IsolationForestDetector Tests
# =============================================================================

def test_isolation_forest_scoring(tmp_path: Path):
    """Verify Isolation Forest scores outliers higher than nominal inliers."""
    rng = np.random.default_rng(42)
    N, d = 100, 10
    X_train = rng.normal(0.0, 1.0, (N, d))

    iso = IsolationForestDetector(contamination=0.05, n_estimators=60, random_state=42)
    iso.fit(X_train)
    assert iso.is_fitted is True

    # Nominal point
    nom_score, is_nom_anom = iso.score(np.zeros(d))
    assert 0.0 <= nom_score <= 1.0

    # Extreme outlier
    outlier_score, is_out_anom = iso.score(np.full(d, 25.0))
    assert outlier_score > nom_score
    assert is_out_anom is True

    # Test serialization
    model_path = tmp_path / "test_iso.joblib"
    iso.save(model_path)
    loaded_iso = IsolationForestDetector.load(model_path)
    assert loaded_iso.is_fitted is True


# =============================================================================
# 4. IncidentClassifier Tests
# =============================================================================

def test_incident_classifier_training_and_confidence(tmp_path: Path):
    """Verify supervised classifier predicts multi-class archetypes with confidence."""
    generator = MultiTierTelemetryGenerator(seed=42)
    snaps = []

    # Nominal + 2 Archetypes
    snaps.extend(generator.generate_batch(num_snapshots=40, archetype=AnomalyArchetype.NOMINAL))
    snaps.extend(generator.generate_batch(num_snapshots=40, archetype=AnomalyArchetype.DB_CONNECTION_POOL_SATURATION))
    snaps.extend(generator.generate_batch(num_snapshots=40, archetype=AnomalyArchetype.PAYMENT_GATEWAY_OUTAGE))

    df = MultiTierTelemetryGenerator.to_dataframe(snaps)
    extractor = TelemetryFeatureExtractor(window_size=5)
    X, y, feature_names = extractor.fit_transform(df)

    clf = IncidentClassifier(n_estimators=40, max_depth=3, feature_names=feature_names, random_state=42)
    clf.fit(X, y)
    assert clf.is_fitted is True

    # Predict DB Connection Pool Saturation
    db_sat_snap = generator.generate_snapshot(archetype=AnomalyArchetype.DB_CONNECTION_POOL_SATURATION)
    db_vec = extractor.transform_snapshot(db_sat_snap)
    pred_id, pred_name, conf, probs = clf.predict(db_vec)

    assert pred_id == ARCHETYPE_LABEL_MAP[AnomalyArchetype.DB_CONNECTION_POOL_SATURATION.value]
    assert pred_name == AnomalyArchetype.DB_CONNECTION_POOL_SATURATION.value
    assert conf > 0.50
    assert pytest.approx(sum(probs.values()), abs=1e-3) == 1.0

    # Test serialization
    clf_path = tmp_path / "test_clf.joblib"
    clf.save(clf_path)
    loaded_clf = IncidentClassifier.load(clf_path)
    assert loaded_clf.is_fitted is True
