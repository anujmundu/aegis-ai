"""Retriever Agent Node for AegisAI Multi-Agent Reliability Graph.

Role:
- Synthesizes diagnostic queries based on primary driver telemetry and classifier predictions.
- Queries the Hybrid RAG engine (BM25 + Dense Semantic + RRF) across runbooks and postmortems.
- Extracts grounded citations for downstream investigator synthesis.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from ai.agents.state import AgentState
from ai.rag.hybrid import HybridRetriever
from ai.rag.models import RetrievedEvidence, SearchQuery


class RetrieverAgent:
    """Specialized agent node retrieving authoritative runbooks and incident postmortems."""

    def __init__(
        self,
        name: str = "retriever",
        retriever: Optional[HybridRetriever] = None,
        knowledge_base_dir: Optional[Path] = None,
        memory_coordinator: Optional[Any] = None,
    ) -> None:
        self.name = name
        self.memory_coordinator = memory_coordinator
        if retriever is not None:
            self.retriever = retriever
        else:
            self.retriever = HybridRetriever(rrf_k=60)
            kb_dir = knowledge_base_dir or (
                Path(__file__).resolve().parent.parent.parent / "data" / "knowledge_base"
            )
            if kb_dir.exists():
                self.retriever.index_directory(kb_dir)

    def _build_diagnostic_query(self, state: AgentState) -> str:
        """Construct high-relevance search query from state evidence."""
        query_parts: List[str] = [state.service_id]

        if state.primary_driver:
            m = state.primary_driver.metric_name
            query_parts.append(m)
            if "pool" in m or "query_latency" in m:
                query_parts.append("PostgreSQL connection pool max_connections saturation")
            elif "memory" in m:
                query_parts.append("memory leak garbage collection stop-the-world heap restart")
            elif "latency" in m or "error_rate" in m:
                query_parts.append("timeout circuit breaker downstream failure")
            elif "checkout" in m or "order" in m or "revenue" in m:
                query_parts.append("payment gateway failure failover decline")

        if state.classifier_archetype:
            query_parts.append(state.classifier_archetype.replace("_", " "))

        return " ".join(query_parts)

    def execute(self, state: AgentState) -> Dict[str, Any]:
        """Execute hybrid search and populate citations."""
        query_text = self._build_diagnostic_query(state)
        sq = SearchQuery(query_text=query_text, service_id=state.service_id, top_k=4, min_relevance=0.35)

        evidence: List[RetrievedEvidence] = self.retriever.retrieve(sq)

        citations: List[Dict[str, str]] = []
        for e in evidence:
            citations.append({
                "citation": e.citation,
                "source_uri": e.chunk.source_uri,
                "section": e.chunk.section_title,
                "chunk_id": e.chunk.chunk_id,
                "rerank_score": str(e.rerank_score),
            })

        hist_summary: Optional[str] = None
        if self.memory_coordinator:
            p_metric = state.primary_driver.metric_name if state.primary_driver else None
            recall_ctx = self.memory_coordinator.recall_experience(
                service_id=state.service_id,
                primary_driver_metric=p_metric,
                diagnostic_query=query_text,
                limit=3,
            )
            hist_summary = recall_ctx.formatted_summary

        audit_entry = {
            "agent": self.name,
            "action": "RETRIEVE_EVIDENCE",
            "query": query_text,
            "retrieved_count": len(evidence),
            "top_citation": citations[0]["citation"] if citations else "none",
            "has_memory_recall": bool(hist_summary),
        }

        return {
            "retrieved_evidence": evidence,
            "citations": citations,
            "historical_context": hist_summary,
            "audit_log": state.audit_log + [audit_entry],
        }
