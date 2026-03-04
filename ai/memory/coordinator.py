"""Unified Operational Memory Coordinator for AegisAI.

Bridges:
- Tier 1: Working Memory (Redis / Local in-memory session scratchpad)
- Tier 2: Episodic Memory (Relational historical incidents, signals & remediation audits)
- Tier 3: Semantic Memory (Vectorized embeddings of postmortems & lessons learned)

Provides an institutional memory recall engine allowing agents to learn from past incidents.
"""

import logging
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ai.agents.state import AgentState
from ai.memory.episodic import EpisodicMemory
from ai.memory.semantic import SemanticMemory, SemanticMemoryMatch
from ai.memory.working import WorkingMemory

logger = logging.getLogger("aegisai.memory.coordinator")


class HistoricalIncidentContext(BaseModel):
    """Synthesized institutional memory context returned to diagnostic agents."""

    service_id: str
    total_past_episodes: int
    similar_incidents: List[Dict[str, Any]] = Field(default_factory=list)
    semantic_matches: List[SemanticMemoryMatch] = Field(default_factory=list)
    recommended_remediations: List[str] = Field(default_factory=list)
    recurrent_pattern_warning: Optional[str] = None
    formatted_summary: str = ""


class OperationalMemoryCoordinator:
    """Central Memory Hub orchestrating Tier 1, Tier 2, and Tier 3 memory layers."""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        db_path: Optional[str] = None,
        knowledge_base_dir: Optional[Path] = None,
        auto_bootstrap: bool = True,
    ) -> None:
        self.working = WorkingMemory(redis_url=redis_url)
        self.episodic = EpisodicMemory(db_path=db_path)
        self.semantic = SemanticMemory()

        if auto_bootstrap:
            kb_dir = knowledge_base_dir or (
                Path(__file__).resolve().parent.parent.parent
                / "data"
                / "knowledge_base"
                / "postmortems"
            )
            if kb_dir.exists():
                self.bootstrap_from_postmortems(kb_dir)

    def bootstrap_from_postmortems(self, postmortems_dir: Path) -> int:
        """Parse existing Markdown postmortems and seed both Episodic and Semantic memories."""
        count = 0
        for md_file in postmortems_dir.glob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                # Extract Title
                title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
                title = title_match.group(1).strip() if title_match else md_file.stem

                # Extract Incident ID
                inc_id = f"PM-{md_file.stem}"
                for line in content.splitlines():
                    if "Incident ID" in line and "`" in line:
                        parts = line.split("`")
                        if len(parts) >= 2:
                            inc_id = parts[1].strip()
                            break

                # Extract Impacted Service
                service_id = "checkout-service"
                for line in content.splitlines():
                    if "Impacted Services" in line and "`" in line:
                        parts = line.split("`")
                        if len(parts) >= 2:
                            service_id = parts[1].strip()
                            break

                # Extract Root cause keywords
                tags = [service_id]
                content_lower = content.lower()
                if "connection pool" in content_lower:
                    tags.extend(["db_pool", "database", "aurora", "db_connection_pool_active_connections"])
                if "memory leak" in content_lower:
                    tags.extend(["memory", "oom", "gc_pause", "infra_memory_percent"])
                if "payment" in content_lower:
                    tags.extend(["payment", "stripe", "checkout", "biz_checkout_success_rate"])
                if "partner" in content_lower or "hang" in content_lower:
                    tags.extend(["third_party", "timeout", "circuit_breaker", "app_http_error_rate_5xx"])

                # 1. Seed Semantic Memory
                self.semantic.add_entry(
                    incident_id=inc_id,
                    service_id=service_id,
                    title=title,
                    content=content,
                    tags=tags,
                )

                # 2. Seed Episodic Memory
                now_str = datetime.now(timezone.utc).isoformat()
                with self.episodic._conn:
                    self.episodic._conn.execute(
                        """
                        INSERT OR IGNORE INTO services (id, name, created_at)
                        VALUES (?, ?, ?)
                        """,
                        (service_id, f"Service {service_id}", now_str),
                    )
                    self.episodic._conn.execute(
                        """
                        INSERT OR REPLACE INTO incidents (
                            id, title, severity, status, service_id, detected_at, resolved_at,
                            primary_driver_metric, primary_deviation_sigma, root_cause_hypothesis,
                            confidence_score, postmortem_markdown, classifier_archetype, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            inc_id,
                            title,
                            "CRITICAL",
                            "RESOLVED",
                            service_id,
                            now_str,
                            now_str,
                            "db_connection_pool_active_connections" if "db_pool" in tags else "latency_p99_ms",
                            5.5,
                            f"Historical postmortem record from {md_file.name}",
                            1.0,
                            content,
                            "DB_CONNECTION_POOL_SATURATION" if "db_pool" in tags else "GENERAL_OUTAGE",
                            now_str,
                            now_str,
                        ),
                    )
                count += 1
            except Exception as e:
                logger.error("Error bootstrapping postmortem %s: %s", md_file, e)

        return count

    # --- Tier 1 Operations ---
    def checkpoint_active_investigation(self, state: AgentState) -> None:
        """Save active agent investigation state into Tier 1 Working Memory."""
        self.working.set_state(state)

    def get_active_investigation(self, incident_id: str) -> Optional[AgentState]:
        """Load active agent investigation state from Tier 1 Working Memory."""
        return self.working.get_state(incident_id)

    # --- Tier 2 & 3 Combined Persistence ---
    def finalize_incident(
        self, state: AgentState, postmortem_md: Optional[str] = None
    ) -> str:
        """Commit a resolved or mitigated incident to Episodic and Semantic memories."""
        # 1. Write to Relational Episodic Memory
        inc_id = self.episodic.record_incident(state, postmortem_md=postmortem_md)

        # 2. Index into Semantic Memory
        p_metric = state.primary_driver.metric_name if state.primary_driver else ""
        content = (
            f"Service: {state.service_id}\n"
            f"Primary Metric: {p_metric}\n"
            f"Hypothesis: {state.root_cause_hypothesis or ''}\n"
            f"Reasoning: {' '.join(state.reasoning_trace)}\n"
            f"Execution: {state.execution_result or 'None'}\n"
            f"Postmortem Content:\n{postmortem_md or ''}"
        )
        title = f"Postmortem: {state.service_id} ({state.classifier_archetype or 'Incident'})"
        tags = [state.service_id]
        if p_metric:
            tags.append(p_metric)
        if state.classifier_archetype:
            tags.append(state.classifier_archetype)

        self.semantic.add_entry(
            incident_id=state.incident_id,
            service_id=state.service_id,
            title=title,
            content=content,
            tags=tags,
        )

        # 3. Clean up Tier 1 Working Memory
        self.working.delete_state(state.incident_id)
        return inc_id

    # --- Experience Recall Query ---
    def recall_experience(
        self,
        service_id: str,
        primary_driver_metric: Optional[str] = None,
        diagnostic_query: Optional[str] = None,
        limit: int = 3,
    ) -> HistoricalIncidentContext:
        """Synthesize past incident history, successful remediations, and semantic postmortem matches."""
        # 1. Pull relational past episodes
        past_episodes = self.episodic.find_similar_incidents(
            service_id=service_id,
            primary_metric=primary_driver_metric,
            limit=limit,
        )

        # 2. Pull semantic vector matches
        search_query = diagnostic_query or f"{service_id} {primary_driver_metric or ''}"
        semantic_matches = self.semantic.search(
            query=search_query,
            top_k=limit,
            service_filter=service_id,
        )

        # 3. Aggregate successful remediation actions
        remediation_actions: List[str] = []
        for ep in past_episodes:
            rem = ep.get("applied_remediation")
            if rem and rem.get("action_type"):
                remediation_actions.append(rem["action_type"])

        ranked_remediations = [item for item, _ in Counter(remediation_actions).most_common()]

        # 4. Detect Recurrent Patterns
        recurrent_warning = None
        if len(past_episodes) >= 2:
            recurrent_warning = (
                f"WARNING: Service '{service_id}' has suffered {len(past_episodes)} similar incidents "
                f"involving metric '{primary_driver_metric}'. Root cause may indicate an unaddressed systemic defect."
            )

        # 5. Format Readable Summary for Agent Consumption
        lines = [
            f"### Institutional Memory Recall for '{service_id}':",
            f"- Historical Incidents on Record: {len(past_episodes)}",
        ]
        if ranked_remediations:
            lines.append(f"- Previously Successful Remediations: {', '.join(ranked_remediations)}")
        if recurrent_warning:
            lines.append(f"- {recurrent_warning}")
        if semantic_matches:
            lines.append("- Relevant Historical Postmortems:")
            for m in semantic_matches:
                lines.append(
                    f"  * [{m.entry.title}] (Similarity: {m.similarity_score:.1%}, Grade: {m.relevance_grade})"
                )

        summary_text = "\n".join(lines)

        return HistoricalIncidentContext(
            service_id=service_id,
            total_past_episodes=len(past_episodes),
            similar_incidents=past_episodes,
            semantic_matches=semantic_matches,
            recommended_remediations=ranked_remediations,
            recurrent_pattern_warning=recurrent_warning,
            formatted_summary=summary_text,
        )
