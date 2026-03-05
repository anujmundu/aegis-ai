"""Tier 3 Semantic Memory for AegisAI Operational Reliability Platform.

Maintains dense vector semantic embeddings over historical incident postmortems,
root cause analyses, and institutional SRE lessons learned.

Enables semantic retrieval of past incident resolutions based on failure symptom descriptions.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import numpy as np
from pydantic import BaseModel, Field
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger("aegisai.memory.semantic")


class SemanticMemoryEntry(BaseModel):
    """Entry stored in Tier 3 Semantic Vector Memory."""

    entry_id: str = Field(..., description="Unique memory entry ID")
    incident_id: str
    service_id: str
    title: str
    content: str
    tags: List[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SemanticMemoryMatch(BaseModel):
    """Match result returned from semantic memory similarity search."""

    entry: SemanticMemoryEntry
    similarity_score: float
    relevance_grade: str = Field(
        default="HIGH", description="HIGH (>=0.7) | MEDIUM (>=0.4) | LOW (<0.4)"
    )


class SemanticMemory:
    """Tier 3 Semantic Vector Memory store."""

    def __init__(self) -> None:
        self.entries: List[SemanticMemoryEntry] = []
        self.vectorizer = TfidfVectorizer(
            analyzer="word",
            ngram_range=(1, 2),
            sublinear_tf=True,
            min_df=1,
            lowercase=True,
        )
        self.embeddings: Optional[np.ndarray] = None
        self.is_indexed: bool = False

    def add_entry(
        self,
        incident_id: str,
        service_id: str,
        title: str,
        content: str,
        tags: Optional[List[str]] = None,
    ) -> str:
        """Add an incident postmortem or lesson learned into semantic memory."""
        entry_id = f"sem-{incident_id}-{len(self.entries)}"
        entry = SemanticMemoryEntry(
            entry_id=entry_id,
            incident_id=incident_id,
            service_id=service_id,
            title=title,
            content=content,
            tags=tags or [],
        )
        self.entries.append(entry)
        self._reindex()
        return entry_id

    def _reindex(self) -> None:
        """Recompute TF-IDF vector embeddings over all stored semantic entries."""
        if not self.entries:
            self.embeddings = None
            self.is_indexed = False
            return

        corpus = [
            f"{e.service_id} {e.title} {' '.join(e.tags)} {e.content}"
            for e in self.entries
        ]
        self.embeddings = self.vectorizer.fit_transform(corpus)
        self.is_indexed = True

    def search(
        self,
        query: str,
        top_k: int = 3,
        service_filter: Optional[str] = None,
        min_similarity: float = 0.05,
    ) -> List[SemanticMemoryMatch]:
        """Perform semantic similarity search over historical incident postmortems."""
        if not self.is_indexed or self.embeddings is None or not self.entries:
            return []

        q_vec = self.vectorizer.transform([query])
        similarities = cosine_similarity(q_vec, self.embeddings)[0]

        ranked_indices = np.argsort(similarities)[::-1]
        matches: List[SemanticMemoryMatch] = []

        for idx in ranked_indices:
            sim = float(similarities[idx])
            if sim < min_similarity:
                continue

            entry = self.entries[idx]
            if service_filter and entry.service_id != service_filter:
                continue

            grade = "HIGH" if sim >= 0.65 else ("MEDIUM" if sim >= 0.35 else "LOW")
            matches.append(
                SemanticMemoryMatch(
                    entry=entry,
                    similarity_score=round(sim, 4),
                    relevance_grade=grade,
                )
            )
            if len(matches) >= top_k:
                break

        return matches

    def save_to_file(self, filepath: Path) -> None:
        """Serialize semantic memory entries to JSON file."""
        data = [e.model_dump() for e in self.entries]
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def load_from_file(self, filepath: Path) -> None:
        """Load semantic memory entries from JSON file and rebuild index."""
        if not filepath.exists():
            return
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.entries = [SemanticMemoryEntry(**d) for d in data]
        self._reindex()
