"""Dependency Injection Providers for AegisAI FastAPI Microservice.

Provides pre-warmed singletons for:
- Settings
- Data Contract Validator
- Statistical Anomaly Detection Engine
- ML Inference Ensemble (Feature Extractor, Autoencoder, Isolation Forest, XGBoost Classifier)
- Hybrid RAG Retriever
- 3-Tier Operational Memory Coordinator
- Multi-Agent Reliability Graph Orchestrator
"""

import logging
from functools import lru_cache
from pathlib import Path

from ai.agents.graph import ReliabilityGraph
from ai.memory.coordinator import OperationalMemoryCoordinator
from ai.rag.hybrid import HybridRetriever
from apps.api.config import Settings
from data.schemas.events import AnomalyArchetype
from data.synthetic.telemetry_generator import MultiTierTelemetryGenerator
from data.validation.data_contract import DataContractValidator
from ml.features.feature_extractor import TelemetryFeatureExtractor
from ml.models.classical.incident_classifier import IncidentClassifier
from ml.models.classical.isolation_forest import IsolationForestDetector
from ml.models.deep.autoencoder import ReconstructionAutoencoder
from ml.models.statistical.engine import StatisticalAnomalyEngine

logger = logging.getLogger("aegisai.api.dependencies")

# Root path for repository
BASE_DIR = Path(__file__).resolve().parent.parent.parent


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()


@lru_cache(maxsize=1)
def get_contract_validator() -> DataContractValidator:
    """Return cached DataContractValidator."""
    return DataContractValidator()


@lru_cache(maxsize=1)
def get_statistical_engine() -> StatisticalAnomalyEngine:
    """Return pre-calibrated statistical detector engine."""
    engine = StatisticalAnomalyEngine(service_id="checkout-service")
    # Warm up / calibrate with nominal synthetic historical data
    gen = MultiTierTelemetryGenerator(seed=42)
    history = gen.generate_batch(num_snapshots=60, archetype=AnomalyArchetype.NOMINAL)
    engine.fit_baseline(history)
    logger.info("StatisticalAnomalyEngine calibrated with nominal historical snapshots.")
    return engine


class MLEnsembleContainer:
    """Container holding pre-trained ML models."""

    def __init__(
        self,
        extractor: TelemetryFeatureExtractor,
        autoencoder: ReconstructionAutoencoder,
        isolation_forest: IsolationForestDetector,
        classifier: IncidentClassifier,
    ) -> None:
        self.extractor = extractor
        self.autoencoder = autoencoder
        self.isolation_forest = isolation_forest
        self.classifier = classifier


@lru_cache(maxsize=1)
def get_ml_ensemble() -> MLEnsembleContainer:
    """Initialize and warm up all classical and deep ML models."""
    extractor = TelemetryFeatureExtractor(window_size=5)
    gen = MultiTierTelemetryGenerator(seed=42)

    snaps = []
    # Generate balanced snapshots across all archetypes
    for arch in AnomalyArchetype:
        batch = gen.generate_batch(num_snapshots=25, archetype=arch)
        snaps.extend(batch)

    df = MultiTierTelemetryGenerator.to_dataframe(snaps)
    X, y, feature_names = extractor.fit_transform(df)

    # 1. Deep Autoencoder
    ae = ReconstructionAutoencoder(
        input_dim=X.shape[1],
        hidden_dim=12,
        latent_dim=4,
        threshold_sigmas=2.5,
        feature_names=feature_names,
        seed=42,
    )
    ae.fit(X, epochs=40, batch_size=16, lr=0.01)

    # 2. Isolation Forest
    iso = IsolationForestDetector(contamination=0.05, n_estimators=60, random_state=42)
    iso.fit(X)

    # 3. XGBoost Archetype Classifier
    clf = IncidentClassifier(n_estimators=50, max_depth=4, random_state=42)
    clf.fit(X, y, feature_names=feature_names)

    logger.info("MLEnsembleContainer warmed up successfully with %d features.", X.shape[1])
    return MLEnsembleContainer(extractor, ae, iso, clf)


@lru_cache(maxsize=1)
def get_hybrid_retriever() -> HybridRetriever:
    """Return HybridRetriever indexed over knowledge base."""
    retriever = HybridRetriever(rrf_k=60)
    kb_dir = BASE_DIR / "data" / "knowledge_base"
    if kb_dir.exists():
        retriever.index_directory(kb_dir)
        logger.info("HybridRetriever indexed knowledge base from %s", kb_dir)
    return retriever


@lru_cache(maxsize=1)
def get_memory_coordinator() -> OperationalMemoryCoordinator:
    """Return 3-Tier Operational Memory Coordinator singleton."""
    coord = OperationalMemoryCoordinator(
        knowledge_base_dir=BASE_DIR / "data" / "knowledge_base" / "postmortems",
        auto_bootstrap=True,
    )
    logger.info("OperationalMemoryCoordinator initialized and bootstrapped.")
    return coord


@lru_cache(maxsize=1)
def get_reliability_graph() -> ReliabilityGraph:
    """Return compiled LangGraph ReliabilityGraph orchestrator."""
    retriever = get_hybrid_retriever()
    coordinator = get_memory_coordinator()
    graph = ReliabilityGraph(
        retriever=retriever,
        knowledge_base_dir=BASE_DIR / "data" / "knowledge_base",
        grounding_threshold=0.95,
        max_revisions=2,
        memory_coordinator=coordinator,
    )
    logger.info("ReliabilityGraph orchestrator initialized.")
    return graph
