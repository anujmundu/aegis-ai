"""Hybrid RAG Retrieval Engine with Reciprocal Rank Fusion (RRF) and Grounding.

Combines:
1. Okapi BM25 Lexical Keyword Search
2. Dense Semantic Vector Space Search
3. Reciprocal Rank Fusion (RRF, k=60)
4. Precision Re-ranking & Citation Grounding Generation
"""

from pathlib import Path
from typing import Dict, List, Union

from ai.rag.bm25 import BM25OkapiIndexer
from ai.rag.chunker import MarkdownHierarchicalChunker
from ai.rag.dense import DenseSemanticIndexer
from ai.rag.models import DocumentChunk, RetrievedEvidence, SearchQuery


class HybridRetriever:
    """Enterprise hybrid retrieval engine fusing lexical and semantic signals."""

    def __init__(self, rrf_k: int = 60) -> None:
        self.rrf_k = rrf_k
        self.chunker = MarkdownHierarchicalChunker()
        self.bm25 = BM25OkapiIndexer()
        self.dense = DenseSemanticIndexer()
        self.chunks: List[DocumentChunk] = []
        self.is_indexed: bool = False

    def index_directory(self, dir_path: Union[str, Path]) -> "HybridRetriever":
        """Chunk and index all markdown documents in the specified directory."""
        chunks = self.chunker.chunk_directory(dir_path)
        return self.index_chunks(chunks)

    def index_chunks(self, chunks: List[DocumentChunk]) -> "HybridRetriever":
        """Index pre-chunked documents across both BM25 and Dense indexers."""
        self.chunks = chunks
        self.bm25.index(chunks)
        self.dense.index(chunks)
        self.is_indexed = True
        return self

    def retrieve(self, query: Union[str, SearchQuery]) -> List[RetrievedEvidence]:
        """Execute hybrid search using Reciprocal Rank Fusion and return grounded evidence."""
        if not self.is_indexed or not self.chunks:
            return []

        if isinstance(query, str):
            sq = SearchQuery(query_text=query)
        else:
            sq = query

        fetch_k = max(sq.top_k * 3, 15)

        # 1. BM25 Lexical Search
        bm25_results = self.bm25.search(sq.query_text, top_k=fetch_k)
        # 2. Dense Semantic Search
        dense_results = self.dense.search(sq.query_text, top_k=fetch_k)

        # Build Rank Lookup Tables
        bm25_ranks: Dict[str, int] = {chunk.chunk_id: rank + 1 for rank, (chunk, _) in enumerate(bm25_results)}
        dense_ranks: Dict[str, int] = {chunk.chunk_id: rank + 1 for rank, (chunk, _) in enumerate(dense_results)}

        bm25_score_map: Dict[str, float] = {chunk.chunk_id: score for chunk, score in bm25_results}
        dense_score_map: Dict[str, float] = {chunk.chunk_id: score for chunk, score in dense_results}

        # Normalize BM25 raw scores to [0, 1]
        max_bm25 = max(bm25_score_map.values()) if bm25_score_map else 1.0

        # Combine all retrieved candidate chunk IDs
        candidate_ids = set(bm25_ranks.keys()).union(set(dense_ranks.keys()))
        chunk_map = {c.chunk_id: c for c in self.chunks}

        evidence_list: List[RetrievedEvidence] = []

        for cid in candidate_ids:
            chunk = chunk_map.get(cid)
            if chunk is None:
                continue

            # Optional doc_type filtering ("runbook" vs "postmortem")
            if sq.doc_type and chunk.metadata.get("doc_type") != sq.doc_type:
                continue

            # Compute RRF score: 1 / (k + rank_bm25) + 1 / (k + rank_dense)
            r_bm25 = bm25_ranks.get(cid, 999)
            r_dense = dense_ranks.get(cid, 999)
            rrf_score = (1.0 / (self.rrf_k + r_bm25)) + (1.0 / (self.rrf_k + r_dense))

            # Calibrate final re-rank score [0, 1]
            raw_b = bm25_score_map.get(cid, 0.0)
            norm_b = min(1.0, raw_b / max(1.0, max_bm25))
            sem_score = dense_score_map.get(cid, 0.0)

            # Balanced fusion between lexical match and semantic similarity
            final_rerank = round(float((0.45 * norm_b) + (0.55 * sem_score)), 4)

            # Format verifiable grounded citation
            source_file = Path(chunk.source_uri).name
            citation = f"[{source_file}#{chunk.chunk_id}: {chunk.section_title}]"

            if final_rerank >= sq.min_relevance:
                evidence_list.append(
                    RetrievedEvidence(
                        chunk=chunk,
                        lexical_score=round(raw_b, 4),
                        semantic_score=round(sem_score, 4),
                        rrf_score=round(rrf_score, 6),
                        rerank_score=final_rerank,
                        citation=citation,
                    )
                )

        # Sort descending by final calibrated score (and tie-break by RRF score)
        evidence_list.sort(key=lambda e: (e.rerank_score, e.rrf_score), reverse=True)
        return evidence_list[: sq.top_k]
