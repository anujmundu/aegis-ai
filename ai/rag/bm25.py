"""Okapi BM25 Lexical Keyword Search for Technical & Operational Runbooks.

Provides exact token matching for technical symbols, error codes, CLI flags,
and SQL functions (e.g. max_connections, pg_stat_activity, HTTP 504).
"""

import math
import re
from collections import Counter
from typing import Dict, List, Tuple

from ai.rag.models import DocumentChunk


def tokenize_technical_text(text: str) -> List[str]:
    """Tokenize technical markdown preserving identifiers, error codes, and flags."""
    # Split on whitespace and punctuation except underscores and hyphens inside identifiers
    tokens = re.findall(r"[A-Za-z0-9_#-]+", text.lower())
    # Filter very short single characters unless digits
    return [t for t in tokens if len(t) > 1 or t.isdigit()]


class BM25OkapiIndexer:
    """Pure-Python / NumPy Okapi BM25 indexer."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.chunks: List[DocumentChunk] = []
        self.corpus_size: int = 0
        self.avg_doc_len: float = 0.0
        self.doc_lens: List[int] = []
        self.doc_term_freqs: List[Counter] = []
        self.doc_freqs: Dict[str, int] = {}
        self.idf: Dict[str, float] = {}

    def index(self, chunks: List[DocumentChunk]) -> "BM25OkapiIndexer":
        """Index a list of DocumentChunk instances."""
        self.chunks = chunks
        self.corpus_size = len(chunks)
        if self.corpus_size == 0:
            return self

        self.doc_lens = []
        self.doc_term_freqs = []
        self.doc_freqs = {}

        total_len = 0
        for chunk in chunks:
            text = f"{chunk.doc_title} {chunk.section_title} {chunk.content}"
            tokens = tokenize_technical_text(text)
            length = len(tokens)
            self.doc_lens.append(length)
            total_len += length

            tf = Counter(tokens)
            self.doc_term_freqs.append(tf)

            for token in set(tokens):
                self.doc_freqs[token] = self.doc_freqs.get(token, 0) + 1

        self.avg_doc_len = total_len / max(1, self.corpus_size)

        # Precompute Robertson-Spärck Jones IDF
        self.idf = {}
        for token, df in self.doc_freqs.items():
            # Standard Lucene/Okapi smoothed IDF: ln((N - n + 0.5) / (n + 0.5) + 1.0)
            self.idf[token] = math.log(((self.corpus_size - df + 0.5) / (df + 0.5)) + 1.0)

        return self

    def search(
        self, query: str, top_k: int = 5
    ) -> List[Tuple[DocumentChunk, float]]:
        """Search indexed chunks using Okapi BM25 scoring."""
        if self.corpus_size == 0:
            return []

        query_tokens = tokenize_technical_text(query)
        if not query_tokens:
            return []

        scores: List[float] = [0.0] * self.corpus_size

        for token in query_tokens:
            if token not in self.idf:
                continue
            idf_val = self.idf[token]

            for doc_idx in range(self.corpus_size):
                tf = self.doc_term_freqs[doc_idx].get(token, 0)
                if tf == 0:
                    continue
                doc_len = self.doc_lens[doc_idx]
                numerator = tf * (self.k1 + 1.0)
                denominator = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / self.avg_doc_len))
                scores[doc_idx] += idf_val * (numerator / denominator)

        ranked_indices = sorted(range(self.corpus_size), key=lambda i: scores[i], reverse=True)
        results: List[Tuple[DocumentChunk, float]] = []
        for idx in ranked_indices[:top_k]:
            if scores[idx] > 0.0:
                results.append((self.chunks[idx], round(float(scores[idx]), 4)))

        return results
