"""Tier 2 Episodic Memory for AegisAI Operational Reliability Platform.

Persists long-term relational history of resolved incidents, evidence chains,
remediation audit records, and generated postmortems.

Architecture:
- Compatible with PostgreSQL (via psycopg/SQLAlchemy) and SQLite (zero-dependency local mode).
- Matches data/schemas/init_db.sql schema definitions.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ai.agents.state import AgentState
from data.schemas.events import IncidentStatus

logger = logging.getLogger("aegisai.memory.episodic")


class EpisodicMemory:
    """Tier 2 Episodic Memory engine for institutional reliability learning."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        """Initialize Episodic Memory.

        Args:
            db_path: Path to SQLite database file. If ':memory:' or None, uses in-memory DB.
        """
        self.db_path = db_path or ":memory:"
        self._conn = self._init_db()

    def _init_db(self) -> sqlite3.Connection:
        """Create database connection and initialize relational schema."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row

        with conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS services (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    tier TEXT NOT NULL DEFAULT 'application',
                    criticality TEXT NOT NULL DEFAULT 'HIGH',
                    owner_team TEXT NOT NULL DEFAULT 'platform-sre',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    detected_at TEXT NOT NULL,
                    resolved_at TEXT,
                    primary_driver_metric TEXT,
                    primary_deviation_sigma REAL,
                    root_cause_hypothesis TEXT,
                    confidence_score REAL,
                    postmortem_markdown TEXT,
                    classifier_archetype TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS incident_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id TEXT NOT NULL,
                    signal_name TEXT NOT NULL,
                    detector_type TEXT NOT NULL,
                    observed_value REAL NOT NULL,
                    baseline_value REAL NOT NULL,
                    deviation_sigma REAL NOT NULL,
                    is_primary_driver INTEGER NOT NULL DEFAULT 0,
                    detected_at TEXT NOT NULL,
                    FOREIGN KEY (incident_id) REFERENCES incidents(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS incident_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,
                    source_uri TEXT NOT NULL,
                    chunk_id TEXT,
                    citation_text TEXT NOT NULL,
                    grounding_score REAL NOT NULL DEFAULT 1.0,
                    retrieved_at TEXT NOT NULL,
                    FOREIGN KEY (incident_id) REFERENCES incidents(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS remediation_audit (
                    id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    target_resource TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    risk_level TEXT NOT NULL DEFAULT 'LOW',
                    status TEXT NOT NULL DEFAULT 'PROPOSED',
                    requires_human_approval INTEGER NOT NULL DEFAULT 1,
                    is_approved INTEGER NOT NULL DEFAULT 0,
                    approval_token TEXT,
                    execution_result TEXT,
                    proposed_at TEXT NOT NULL,
                    executed_at TEXT,
                    FOREIGN KEY (incident_id) REFERENCES incidents(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_incidents_service ON incidents(service_id, detected_at DESC);
                CREATE INDEX IF NOT EXISTS idx_incidents_driver ON incidents(primary_driver_metric);
                CREATE INDEX IF NOT EXISTS idx_signals_incident ON incident_signals(incident_id);
                CREATE INDEX IF NOT EXISTS idx_remediation_incident ON remediation_audit(incident_id);
            """)

        return conn

    def record_incident(self, state: AgentState, postmortem_md: Optional[str] = None) -> str:
        """Record a completed or in-progress incident into episodic memory."""
        now_str = datetime.now(timezone.utc).isoformat()
        resolved_str = (
            now_str if state.status in [IncidentStatus.RESOLVED, IncidentStatus.REMEDIATION_EXECUTED] else None
        )

        p_metric = state.primary_driver.metric_name if state.primary_driver else None
        p_sigma = state.primary_driver.deviation_sigma if state.primary_driver else None

        with self._conn:
            # 1. Upsert Service
            self._conn.execute(
                """
                INSERT INTO services (id, name, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (state.service_id, f"Service {state.service_id}", now_str),
            )

            # 2. Upsert Incident
            title = f"Incident on {state.service_id}: {p_metric or 'Anomaly Detected'}"
            self._conn.execute(
                """
                INSERT INTO incidents (
                    id, title, severity, status, service_id, detected_at, resolved_at,
                    primary_driver_metric, primary_deviation_sigma, root_cause_hypothesis,
                    confidence_score, postmortem_markdown, classifier_archetype, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    resolved_at=excluded.resolved_at,
                    root_cause_hypothesis=excluded.root_cause_hypothesis,
                    confidence_score=excluded.confidence_score,
                    postmortem_markdown=COALESCE(excluded.postmortem_markdown, incidents.postmortem_markdown),
                    updated_at=excluded.updated_at
                """,
                (
                    state.incident_id,
                    title,
                    state.severity.value,
                    state.status.value,
                    state.service_id,
                    state.detected_at.isoformat(),
                    resolved_str,
                    p_metric,
                    p_sigma,
                    state.root_cause_hypothesis,
                    state.confidence_score,
                    postmortem_md,
                    state.classifier_archetype,
                    now_str,
                    now_str,
                ),
            )

            # 3. Insert Signals
            if state.raw_signals:
                self._conn.execute(
                    "DELETE FROM incident_signals WHERE incident_id = ?", (state.incident_id,)
                )
                signal_rows = [
                    (
                        state.incident_id,
                        s.metric_name,
                        s.detector_type,
                        s.observed_value,
                        s.baseline_value,
                        s.deviation_sigma,
                        1 if s.is_primary_driver else 0,
                        s.timestamp.isoformat(),
                    )
                    for s in state.raw_signals
                ]
                self._conn.executemany(
                    """
                    INSERT INTO incident_signals (
                        incident_id, signal_name, detector_type, observed_value, baseline_value,
                        deviation_sigma, is_primary_driver, detected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    signal_rows,
                )

            # 4. Insert Citations
            if state.citations:
                self._conn.execute(
                    "DELETE FROM incident_evidence WHERE incident_id = ?", (state.incident_id,)
                )
                cite_rows = [
                    (
                        state.incident_id,
                        "RUNBOOK",
                        c.get("source_uri", "unknown"),
                        c.get("chunk_id", "unknown"),
                        c.get("citation", ""),
                        state.grounding_score,
                        now_str,
                    )
                    for c in state.citations
                ]
                self._conn.executemany(
                    """
                    INSERT INTO incident_evidence (
                        incident_id, evidence_type, source_uri, chunk_id, citation_text, grounding_score, retrieved_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    cite_rows,
                )

            # 5. Insert Remediation Audit
            if state.remediation_proposal:
                p = state.remediation_proposal
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO remediation_audit (
                        id, incident_id, action_type, target_resource, parameters_json,
                        risk_level, status, requires_human_approval, is_approved, approval_token,
                        execution_result, proposed_at, executed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"AUD-{state.incident_id}",
                        state.incident_id,
                        p.action_type,
                        p.target_resource,
                        json.dumps(p.parameters),
                        p.risk_level,
                        state.status.value,
                        1 if state.requires_human_approval else 0,
                        1 if state.is_approved else 0,
                        state.approval_token,
                        state.execution_result,
                        now_str,
                        now_str if state.is_approved else None,
                    ),
                )

        return state.incident_id

    def get_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve full details of an incident by ID."""
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,))
        inc_row = cursor.fetchone()
        if not inc_row:
            return None

        inc = dict(inc_row)

        # Fetch signals
        cursor.execute("SELECT * FROM incident_signals WHERE incident_id = ?", (incident_id,))
        inc["signals"] = [dict(r) for r in cursor.fetchall()]

        # Fetch evidence
        cursor.execute("SELECT * FROM incident_evidence WHERE incident_id = ?", (incident_id,))
        inc["evidence"] = [dict(r) for r in cursor.fetchall()]

        # Fetch remediation
        cursor.execute("SELECT * FROM remediation_audit WHERE incident_id = ?", (incident_id,))
        rem_rows = cursor.fetchall()
        inc["remediations"] = [dict(r) for r in rem_rows]

        return inc

    def find_similar_incidents(
        self,
        service_id: str,
        primary_metric: Optional[str] = None,
        archetype: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Find historical incidents with matching failure signatures to accelerate diagnosis."""
        cursor = self._conn.cursor()
        query = "SELECT * FROM incidents WHERE service_id = ?"
        params: List[Any] = [service_id]

        if primary_metric:
            query += " AND primary_driver_metric = ?"
            params.append(primary_metric)

        if archetype:
            query += " AND classifier_archetype = ?"
            params.append(archetype)

        query += " ORDER BY detected_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        results: List[Dict[str, Any]] = []

        for row in rows:
            inc_dict = dict(row)
            # Pull successful remediation if available
            cursor.execute(
                """
                SELECT action_type, target_resource, execution_result
                FROM remediation_audit
                WHERE incident_id = ?
                ORDER BY proposed_at DESC LIMIT 1
                """,
                (inc_dict["id"],),
            )
            rem = cursor.fetchone()
            inc_dict["applied_remediation"] = dict(rem) if rem else None
            results.append(inc_dict)

        return results

    def list_all_incidents(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List recent incidents ordered by detection timestamp."""
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM incidents ORDER BY detected_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in cursor.fetchall()]
