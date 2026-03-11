"""Central configuration management for AegisAI Platform.

Follows 12-factor application design using Pydantic Settings v2.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global configuration settings for AegisAI."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Core Environment
    environment: str = Field(default="development", description="Runtime environment")
    service_name: str = Field(default="aegis-ai", description="Microservice identifier")
    debug: bool = Field(default=False, description="Debug flag")

    # API Configuration
    api_host: str = Field(default="0.0.0.0", description="FastAPI host")
    api_port: int = Field(default=8000, description="FastAPI port")
    api_workers: int = Field(default=2, description="Uvicorn workers")

    # Storage & Persistence Layer
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/aegis_ai_db",
        description="Async PostgreSQL connection string",
    )
    database_sync_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/aegis_ai_db",
        description="Sync PostgreSQL connection string for migrations",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis connection URI")

    # Vector Knowledge Store (RAG)
    vector_store_type: str = Field(default="faiss", description="faiss | pgvector")
    vector_index_path: str = Field(default="data/vector_index", description="Local index directory")
    embedding_model_name: str = Field(
        default="BAAI/bge-small-en-v1.5", description="Local embedding model identifier"
    )

    # LLM Provider Configuration
    llm_provider: str = Field(default="ollama", description="ollama | openai | azure")
    ollama_base_url: str = Field(default="http://localhost:11434", description="Ollama server URL")
    ollama_model: str = Field(default="qwen2.5-coder:7b", description="Local model name")
    openai_api_key: str = Field(default="", description="Optional OpenAI API key")
    openai_model: str = Field(default="gpt-4o-mini", description="OpenAI model identifier")

    # MLOps & Experiment Tracking
    mlflow_tracking_uri: str = Field(default="http://localhost:5000", description="MLflow server URI")
    mlflow_experiment_name: str = Field(default="aegisai-anomaly-benchmark", description="Experiment")

    # Anomaly Detection & Quality Thresholds
    zscore_threshold: float = Field(default=3.5, description="Dynamic Z-Score anomaly threshold")
    ewma_alpha: float = Field(default=0.2, description="EWMA smoothing factor")
    isolation_forest_contamination: float = Field(default=0.035, description="Contamination factor")
    min_model_precision: float = Field(default=0.90, description="Model Quality Gate precision")
    max_model_fpr: float = Field(default=0.025, description="Model Quality Gate max FPR")
    max_p99_latency_ms: float = Field(default=15.0, description="Max allowed p99 latency")

    # Grounding & Agent Verification
    min_grounding_score: float = Field(default=0.95, description="Minimum grounding citation score")
    max_agent_steps: int = Field(default=8, description="Max execution steps per LangGraph graph")


# Global instantiated settings singleton
settings = Settings()


def get_settings() -> Settings:
    """Return the global Settings instance."""
    return settings
