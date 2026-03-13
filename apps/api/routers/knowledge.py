"""Knowledge Base & Semantic Memory Search Router."""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from ai.memory.coordinator import OperationalMemoryCoordinator
from ai.rag.hybrid import HybridRetriever
from ai.rag.models import SearchQuery
from apps.api.dependencies import get_hybrid_retriever, get_memory_coordinator
from apps.api.schemas import KnowledgeQueryRequest, KnowledgeQueryResponse

router = APIRouter(prefix="/v1/knowledge", tags=["RAG & Knowledge Base"])


@router.post(
    "/query",
    response_model=KnowledgeQueryResponse,
    summary="Hybrid RAG Search Across Runbooks & Postmortems",
    description="Queries authoritative runbooks and postmortems using Okapi BM25 + Dense Semantic Vector retrieval + Reciprocal Rank Fusion (RRF).",
)
def query_knowledge_base(
    req: KnowledgeQueryRequest,
    retriever: HybridRetriever = Depends(get_hybrid_retriever),
) -> KnowledgeQueryResponse:
    """Execute hybrid search across runbook SOPs and postmortems."""
    sq = SearchQuery(
        query_text=req.query,
        service_id=req.service_id,
        top_k=req.top_k,
        min_relevance=0.25,
    )
    evidence = retriever.retrieve(sq)

    citations = [
        {
            "citation": e.citation,
            "source_uri": e.chunk.source_uri,
            "section": e.chunk.section_title,
            "chunk_id": e.chunk.chunk_id,
            "rerank_score": round(e.rerank_score, 4),
            "content_preview": e.chunk.content[:200] + "...",
        }
        for e in evidence
    ]

    return KnowledgeQueryResponse(
        query=req.query,
        total_retrieved=len(citations),
        citations=citations,
    )


@router.post(
    "/search-memory",
    summary="Search Semantic Vector Memory",
    description="Searches historical postmortems in Tier 3 Semantic Vector Memory by cosine similarity.",
)
def search_semantic_memory(
    req: KnowledgeQueryRequest,
    coordinator: OperationalMemoryCoordinator = Depends(get_memory_coordinator),
) -> List[Dict[str, Any]]:
    """Search postmortems in semantic vector memory."""
    matches = coordinator.semantic.search(
        query=req.query,
        top_k=req.top_k,
        service_filter=req.service_id,
    )
    return [
        {
            "incident_id": m.entry.incident_id,
            "service_id": m.entry.service_id,
            "title": m.entry.title,
            "similarity_score": m.similarity_score,
            "relevance_grade": m.relevance_grade,
            "tags": m.entry.tags,
            "preview": m.entry.content[:250] + "...",
        }
        for m in matches
    ]
