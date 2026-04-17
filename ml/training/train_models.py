"""Production Model Training & Validation Pipeline for AegisAI.

Trains:
1. Feature Extractor (Scaler & temporal dynamics)
2. Isolation Forest (Classical unsupervised outlier detector)
3. Deep Reconstruction Autoencoder (Non-linear multi-metric drift detector)
4. Supervised Incident Classifier (XGBoost / Gradient Boosted Archetype Classifier)

Evaluates on a held-out test split, asserts F1-Score >= 0.90, and exports checkpoints.
"""

import json
from pathlib import Path
from typing import Any, Dict

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import classification_report, f1_score
from sklearn.model_selection import train_test_split

from data.schemas.events import AnomalyArchetype
from data.synthetic.telemetry_generator import MultiTierTelemetryGenerator
from ml.features.feature_extractor import (
    ARCHETYPE_LABEL_MAP,
    LABEL_TO_ARCHETYPE,
    TelemetryFeatureExtractor,
)
from ml.models.classical.incident_classifier import IncidentClassifier
from ml.models.classical.isolation_forest import IsolationForestDetector
from ml.models.deep.autoencoder import ReconstructionAutoencoder


def load_or_generate_dataset(data_dir: Path) -> pd.DataFrame:
    """Load existing synthetic dataset or generate a balanced multi-tier dataset."""
    csv_path = data_dir / "sample_telemetry.csv"
    if csv_path.exists():
        print(f"Loading telemetry dataset from {csv_path}...")
        return pd.read_csv(csv_path)

    print("Generating comprehensive multi-tier training dataset...")
    generator = MultiTierTelemetryGenerator(seed=42)
    snapshots = []

    # 150 Nominal snapshots
    snapshots.extend(generator.generate_batch(num_snapshots=150, archetype=AnomalyArchetype.NOMINAL))

    # 60 snapshots each for the 5 archetypes
    for arch in [
        AnomalyArchetype.DB_CONNECTION_POOL_SATURATION,
        AnomalyArchetype.MEMORY_LEAK_GC_PAUSE,
        AnomalyArchetype.CASCADING_THIRD_PARTY_FAILURE,
        AnomalyArchetype.PAYMENT_GATEWAY_OUTAGE,
        AnomalyArchetype.BLACK_FRIDAY_TRAFFIC_BURST,
    ]:
        scenario = generator.generate_incident_scenario(
            archetype=arch,
            total_ticks=70,
            anomaly_start_tick=20,
            anomaly_duration_ticks=35,
        )
        snapshots.extend(scenario)

    df = MultiTierTelemetryGenerator.to_dataframe(snapshots)
    data_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)
    print(f"Saved generated dataset ({len(df)} samples) to {csv_path}")
    return df


def train_and_evaluate(
    project_root: Path,
) -> Dict[str, Any]:
    """Execute complete end-to-end training and evaluation pipeline."""
    raw_dir = project_root / "data" / "raw"
    processed_dir = project_root / "data" / "processed"
    checkpoints_dir = project_root / "models" / "checkpoints"
    processed_dir.mkdir(parents=True, exist_ok=True)
    checkpoints_dir.mkdir(parents=True, exist_ok=True)

    df = load_or_generate_dataset(raw_dir)

    # 1. Train / Test Stratified Split
    y_raw = np.array([ARCHETYPE_LABEL_MAP.get(str(lbl), 0) for lbl in df["ground_truth_label"]], dtype=int)
    train_df, test_df, y_train, y_test = train_test_split(
        df, y_raw, test_size=0.25, random_state=42, stratify=y_raw
    )

    print(f"Dataset split: {len(train_df)} training samples, {len(test_df)} test samples.")

    # 2. Fit Feature Extractor
    print("Fitting TelemetryFeatureExtractor...")
    extractor = TelemetryFeatureExtractor(window_size=10)
    extractor.fit(train_df)
    X_train = extractor.transform(train_df)
    X_test = extractor.transform(test_df)
    feature_names = extractor.feature_names

    # Save feature extractor artifact
    extractor_path = checkpoints_dir / "feature_extractor.joblib"
    joblib.dump(extractor, extractor_path)
    print(f"Saved feature extractor to {extractor_path}")

    # 3. Train Unsupervised Models on Nominal Training Samples
    nominal_mask_train = (y_train == ARCHETYPE_LABEL_MAP[AnomalyArchetype.NOMINAL.value])
    X_nominal_train = X_train[nominal_mask_train]

    print(f"Training Isolation Forest on {len(X_nominal_train)} nominal samples...")
    iso_forest = IsolationForestDetector(contamination=0.03, n_estimators=120, random_state=42)
    iso_forest.fit(X_nominal_train)
    iso_path = checkpoints_dir / "isolation_forest.joblib"
    iso_forest.save(iso_path)
    print(f"Saved Isolation Forest to {iso_path}")

    print(f"Training Deep Reconstruction Autoencoder on {len(X_nominal_train)} nominal samples...")
    autoencoder = ReconstructionAutoencoder(
        input_dim=X_train.shape[1],
        hidden_dim=16,
        latent_dim=6,
        threshold_sigmas=3.0,
        feature_names=feature_names,
        seed=42,
    )
    autoencoder.fit(X_nominal_train, epochs=45, batch_size=16, lr=0.008)
    ae_path = checkpoints_dir / "autoencoder_weights.json"
    autoencoder.save_weights(ae_path)
    print(f"Saved Autoencoder weights to {ae_path}")

    # 4. Train Supervised Multi-Class Incident Classifier
    print("Training Supervised Incident Classifier...")
    clf = IncidentClassifier(
        model_type="xgboost",
        n_estimators=100,
        max_depth=5,
        learning_rate=0.1,
        feature_names=feature_names,
        random_state=42,
    )
    clf.fit(X_train, y_train, feature_names=feature_names)
    clf_path = checkpoints_dir / "incident_classifier.joblib"
    clf.save(clf_path)
    print(f"Saved Incident Classifier to {clf_path}")

    # 5. Evaluate on Held-Out Test Set
    y_pred = [clf.predict(x)[0] for x in X_test]
    macro_f1 = float(f1_score(y_test, y_pred, average="macro"))
    weighted_f1 = float(f1_score(y_test, y_pred, average="weighted"))

    # Isolation Forest anomaly scoring on test set
    iso_scores = [iso_forest.score(x)[1] for x in X_test]
    # Autoencoder anomaly scoring on test set
    ae_scores = [autoencoder.score(x)[1] for x in X_test]

    is_anom_test = (y_test != ARCHETYPE_LABEL_MAP[AnomalyArchetype.NOMINAL.value])
    iso_detection_rate = float(np.mean(np.array(iso_scores)[is_anom_test]))
    ae_detection_rate = float(np.mean(np.array(ae_scores)[is_anom_test]))

    clf_report = classification_report(
        y_test,
        y_pred,
        target_names=[LABEL_TO_ARCHETYPE.get(i, str(i)) for i in range(len(ARCHETYPE_LABEL_MAP))],
        output_dict=True,
    )

    importances = clf.get_feature_importances()
    top_features = list(importances.items())[:8]

    metrics = {
        "macro_f1_score": round(macro_f1, 4),
        "weighted_f1_score": round(weighted_f1, 4),
        "isolation_forest_anomaly_recall": round(iso_detection_rate, 4),
        "autoencoder_anomaly_recall": round(ae_detection_rate, 4),
        "top_features": top_features,
        "classification_report": clf_report,
        "model_checkpoints": {
            "feature_extractor": str(extractor_path),
            "isolation_forest": str(iso_path),
            "autoencoder": str(ae_path),
            "incident_classifier": str(clf_path),
        },
    }

    metrics_path = processed_dir / "model_evaluation_metrics.json"
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    print("\n" + "=" * 60)
    print("MODEL TRAINING & EVALUATION REPORT")
    print("=" * 60)
    print(f"Supervised Classifier Macro F1:    {macro_f1:.4f} (Target >= 0.90)")
    print(f"Supervised Classifier Weighted F1: {weighted_f1:.4f}")
    print(f"Isolation Forest Anomaly Recall:   {iso_detection_rate:.4f}")
    print(f"Deep Autoencoder Anomaly Recall:   {ae_detection_rate:.4f}")
    print("\nTop Predictive Features:")
    for feat, imp in top_features:
        print(f"  - {feat:35s}: {imp:.4f}")
    print("=" * 60)

    # Verification assertion
    assert macro_f1 >= 0.90, f"Macro F1 score {macro_f1:.4f} is below 0.90 threshold"

    return metrics


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent.parent
    train_and_evaluate(root)
