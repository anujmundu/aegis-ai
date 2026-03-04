"""AegisAI 3-Tier Stateful Operational Memory Package.

Provides:
- Tier 1: WorkingMemory (volatile active session & checkpoint cache)
- Tier 2: EpisodicMemory (long-term relational incident & evidence storage)
- Tier 3: SemanticMemory (vectorized postmortem & organizational learning embeddings)
- OperationalMemoryCoordinator: Unified memory interface for autonomous agents
"""

from ai.memory.coordinator import (
    HistoricalIncidentContext,
    OperationalMemoryCoordinator,
)
from ai.memory.episodic import EpisodicMemory
from ai.memory.semantic import (
    SemanticMemory,
    SemanticMemoryEntry,
    SemanticMemoryMatch,
)
from ai.memory.working import InMemoryWorkingStore, WorkingMemory

__all__ = [
    "WorkingMemory",
    "InMemoryWorkingStore",
    "EpisodicMemory",
    "SemanticMemory",
    "SemanticMemoryEntry",
    "SemanticMemoryMatch",
    "HistoricalIncidentContext",
    "OperationalMemoryCoordinator",
]
