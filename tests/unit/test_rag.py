"""Comprehensive Unit Tests for AegisAI Hybrid RAG System.

Covers:
1. MarkdownHierarchicalChunker (structure preservation, code block integrity, slugified IDs)
2. BM25OkapiIndexer (technical token matching, exact code and SQL queries)
3. DenseSemanticIndexer (conceptual semantic cosine retrieval)
4. HybridRetriever (Reciprocal Rank Fusion, grounded citations, domain query precision)
"""

from pathlib import Path

from ai.rag.bm25 import BM25OkapiIndexer
from ai.rag.chunker import MarkdownHierarchicalChunker
from ai.rag.dense import DenseSemanticIndexer
from ai.rag.hybrid import HybridRetriever
from ai.rag.models import DocumentChunk, SearchQuery

# =============================================================================
# 1. Hierarchical Chunker Tests
# =============================================================================

def test_chunker_preserves_headers_and_code_blocks(tmp_path: Path):
    """Verify hierarchical chunker keeps code blocks intact and generates slugified IDs."""
    sample_md = """# SOP-999: Test Runbook Title

## 1. Overview & Signals
This is the overview section explaining the incident symptoms.

## 2. Remediation Script
Execute the following diagnostic query:
```sql
SELECT count(*), state FROM pg_stat_activity WHERE state != 'idle';
```
Ensure connections are drained safely.
"""
    test_file = tmp_path / "rb_test_sample.md"
    test_file.write_text(sample_md, encoding="utf-8")

    chunker = MarkdownHierarchicalChunker(min_chunk_chars=30)
    chunks = chunker.chunk_file(test_file)

    assert len(chunks) >= 2
    # Verify code block was not mutilated
    rem_chunk = next(c for c in chunks if "Remediation Script" in c.section_title)
    assert "```sql" in rem_chunk.content
    assert "pg_stat_activity" in rem_chunk.content
    assert rem_chunk.chunk_id == "rb_test_sample#2-remediation-script"
    assert rem_chunk.doc_title == "SOP-999: Test Runbook Title"


# =============================================================================
# 2. BM25 Lexical Keyword Indexer Tests
# =============================================================================

def test_bm25_technical_token_exact_matching():
    """Verify BM25 matches exact technical keywords and error codes."""
    chunks = [
        DocumentChunk(
            chunk_id="c1",
            source_uri="sop101.md",
            doc_title="DB Runbook",
            section_title="Pool Tuning",
            content="Tune max_connections parameter and inspect pg_stat_activity locks.",
        ),
        DocumentChunk(
            chunk_id="c2",
            source_uri="sop102.md",
            doc_title="Memory Runbook",
            section_title="Heap Profiling",
            content="Execute py-spy dump and check for OOMKilled cgroup events.",
        ),
    ]

    bm25 = BM25OkapiIndexer()
    bm25.index(chunks)

    # Search exact technical identifier
    results = bm25.search("max_connections pg_stat_activity", top_k=2)
    assert len(results) == 1
    assert results[0][0].chunk_id == "c1"
    assert results[0][1] > 0.0

    # Search OOM technical term
    oom_results = bm25.search("OOMKilled py-spy", top_k=2)
    assert len(oom_results) == 1
    assert oom_results[0][0].chunk_id == "c2"


# =============================================================================
# 3. Dense Semantic Vector Indexer Tests
# =============================================================================

def test_dense_semantic_conceptual_retrieval():
    """Verify dense indexer retrieves conceptually equivalent text without exact match."""
    chunks = [
        DocumentChunk(
            chunk_id="c1",
            source_uri="sop101.md",
            doc_title="Database Saturation",
            section_title="Connection Pool",
            content="PostgreSQL database client connections have reached total capacity limit.",
        ),
        DocumentChunk(
            chunk_id="c2",
            source_uri="sop104.md",
            doc_title="Payment Rejection",
            section_title="Credit Card Gateway",
            content="External credit card processor is declining transactions silently.",
        ),
    ]

    dense = DenseSemanticIndexer()
    dense.index(chunks)

    # Query with conceptual phrase
    results = dense.search("database connection pool full and saturated", top_k=1)
    assert len(results) == 1
    assert results[0][0].chunk_id == "c1"
    assert results[0][1] > 0.20

    # Query with payment concept
    pay_results = dense.search("silent checkout payment transaction failure", top_k=1)
    assert len(pay_results) == 1
    assert pay_results[0][0].chunk_id == "c2"


# =============================================================================
# 4. End-to-End Hybrid Retriever & Grounding Citation Tests
# =============================================================================

def test_hybrid_retrieval_on_live_knowledge_base():
    """Verify hybrid retriever indexes real knowledge base and retrieves exact SOPs."""
    kb_dir = Path(__file__).resolve().parent.parent.parent / "data" / "knowledge_base"
    retriever = HybridRetriever(rrf_k=60)
    retriever.index_directory(kb_dir)

    assert retriever.is_indexed is True
    assert len(retriever.chunks) >= 15

    # 1. Test Query: DB Connection Pool Saturation
    q1 = SearchQuery(query_text="PostgreSQL connection pool saturated max_connections", top_k=3)
    ev1 = retriever.retrieve(q1)
    assert len(ev1) > 0
    top_chunk1 = ev1[0].chunk
    assert "db_pool" in top_chunk1.source_uri or "connection_pool" in top_chunk1.chunk_id
    assert ev1[0].rerank_score > 0.40
    assert ev1[0].citation.startswith("[") and ":" in ev1[0].citation

    # 2. Test Query: Payment Gateway Outage
    q2 = SearchQuery(query_text="silent payment gateway decline Adyen failover", top_k=3)
    ev2 = retriever.retrieve(q2)
    assert len(ev2) > 0
    top_chunk2 = ev2[0].chunk
    assert "payment" in top_chunk2.source_uri
    assert any("FAILOVER_PAYMENT_GATEWAY" in e.chunk.content for e in ev2)

    # 3. Test Query: Memory Leak Stop-The-World GC
    q3 = SearchQuery(query_text="memory leak full garbage collection stop-the-world restart", top_k=3)
    ev3 = retriever.retrieve(q3)
    assert len(ev3) > 0
    assert any("RESTART_CONTAINER" in e.chunk.content for e in ev3)

    # 4. Test Query: Cascading 3rd party failure circuit breaker
    q4 = SearchQuery(query_text="fraud detection partner hanging 504 gateway timeout circuit breaker", top_k=3)
    ev4 = retriever.retrieve(q4)
    assert len(ev4) > 0
    assert any("TRIP_CIRCUIT_BREAKER" in e.chunk.content for e in ev4)
