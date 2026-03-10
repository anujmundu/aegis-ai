"""Data contracts and schemas for AegisAI Hybrid RAG."""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class DocumentChunk(BaseModel):
    """Hierarchical chunk extracted from operational runbooks or postmortems."""
    chunk_id: str = Field(..., description="Unique chunk identifier (e.g. doc.md#section-slug)")
    source_uri: str = Field(..., description="Relative or absolute path to source file")
    doc_title: str
    section_title: str
    content: str
    token_count: int = Field(default=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RetrievedEvidence(BaseModel):
    """Retrieved document chunk with multi-stage ranking scores and citation grounding."""
    chunk: DocumentChunk
    lexical_score: float = Field(default=0.0, description="Raw BM25 lexical score")
    semantic_score: float = Field(default=0.0, description="Dense cosine similarity score [0, 1]")
    rrf_score: float = Field(default=0.0, description="Reciprocal Rank Fusion combined score")
    rerank_score: float = Field(default=0.0, description="Final calibrated relevance score [0, 1]")
    citation: str = Field(..., description="Standardized grounded citation string")


class SearchQuery(BaseModel):
    """Query specification for hybrid retrieval."""
    query_text: str
    service_id: Optional[str] = None
    doc_type: Optional[str] = None  # "runbook" | "postmortem" | None
    top_k: int = Field(default=5, ge=1, le=20)
    min_relevance: float = Field(default=0.35, ge=0.0, le=1.0)
