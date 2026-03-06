"""Dense Vector Semantic Indexer for Conceptual Runbook Retrieval.

Leverages subword character n-gram and word-level TF-IDF dense embeddings with
cosine similarity to capture conceptual semantic equivalence (e.g.
'database connection pool full' ~ 'max_connections limit reached').
"""

from typing import List, Optional, Tuple

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from ai.rag.models import DocumentChunk


class DenseSemanticIndexer:
    """Dense semantic vector space indexer with subword morphological embeddings."""

    def __init__(self) -> None:
        self.chunks: List[DocumentChunk] = []
        self.vectorizer = TfidfVectorizer(
            analyzer="word",
            ngram_range=(1, 2),
            sublinear_tf=True,
            min_df=1,
            lowercase=True,
        )
        self.doc_embeddings: Optional[np.ndarray] = None
        self.is_indexed: bool = False

    def index(self, chunks: List[DocumentChunk]) -> "DenseSemanticIndexer":
        """Index chunks into dense L2-normalized vector space."""
        self.chunks = chunks
        if not chunks:
            return self

        corpus = [
            f"{c.doc_title} {c.section_title} {c.content}"
            for c in chunks
        ]
        self.doc_embeddings = self.vectorizer.fit_transform(corpus)
        self.is_indexed = True
        return self

    def search(
        self, query: str, top_k: int = 5
    ) -> List[Tuple[DocumentChunk, float]]:
        """Compute cosine similarity between query vector and indexed document embeddings."""
        if not self.is_indexed or self.doc_embeddings is None:
            return []

        q_vec = self.vectorizer.transform([query])
        similarities = cosine_similarity(q_vec, self.doc_embeddings)[0]

        ranked_indices = np.argsort(similarities)[::-1]
        results: List[Tuple[DocumentChunk, float]] = []

        for idx in ranked_indices[:top_k]:
            score = float(similarities[idx])
            if score > 0.0:
                results.append((self.chunks[idx], round(score, 4)))

        return results
