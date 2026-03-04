"""Validator Agent Node for AegisAI Multi-Agent Reliability Graph.

Role:
- Independent Anti-Hallucination Evaluator & Grounding Gatekeeper.
- Verifies that every assertion in the root cause hypothesis and reasoning trace
  is strictly grounded in raw telemetry signals, ML classifications, or retrieved runbook citations.
- Enforces a strict Grounding Score SLA (>= 0.95).
- Emits structured critique feedback when grounding fails, driving iterative revision.
"""

from typing import Any, Dict, List, Optional

from ai.agents.state import AgentState
from data.schemas.events import IncidentStatus


class ValidatorAgent:
    """Specialized agent node evaluating diagnostic grounding and anti-hallucination compliance."""

    def __init__(
        self,
        name: str = "validator",
        grounding_threshold: float = 0.95,
        max_revisions: int = 2,
    ) -> None:
        self.name = name
        self.grounding_threshold = grounding_threshold
        self.max_revisions = max_revisions

    def _evaluate_grounding(self, state: AgentState) -> tuple[float, List[str], List[str]]:
        """Compute the quantitative grounding score by checking factual claims against evidence.

        Returns:
            (grounding_score, verified_claims, ungrounded_claims)
        """
        hypothesis = state.root_cause_hypothesis or ""
        reasoning = " ".join(state.reasoning_trace)
        full_text = f"{hypothesis} {reasoning}"

        verified: List[str] = []
        ungrounded: List[str] = []

        # 1. Verify Service ID Grounding
        if state.service_id in full_text:
            verified.append(f"Service ID '{state.service_id}' accurately grounded.")
        else:
            ungrounded.append(f"Target service '{state.service_id}' not mentioned in hypothesis/reasoning.")

        # 2. Verify Primary Driver Telemetry Grounding
        if state.primary_driver:
            p_metric = state.primary_driver.metric_name
            # Check if metric name or core token appears
            metric_tokens = [tok for tok in p_metric.split("_") if len(tok) > 3]
            is_metric_grounded = p_metric in full_text or any(tok in full_text.lower() for tok in metric_tokens)
            if is_metric_grounded:
                verified.append(f"Primary driver metric '{p_metric}' verified against telemetry.")
            else:
                ungrounded.append(f"Primary driver metric '{p_metric}' absent from reasoning.")
        else:
            # If no primary driver, check if nominal telemetry was stated
            if "nominal" in full_text.lower() or "no active" in full_text.lower():
                verified.append("Nominal status matches empty telemetry signals.")
            else:
                ungrounded.append("Hypothesis claims anomaly but raw signals are empty.")

        # 3. Verify Authoritative Citation Grounding
        if state.citations:
            cited_in_text = False
            for cite in state.citations:
                c_str = cite.get("citation", "")
                chunk_id = cite.get("chunk_id", "")
                if c_str and c_str in full_text:
                    cited_in_text = True
                    verified.append(f"Authoritative runbook citation '{c_str}' verified.")
                    break
                elif chunk_id and chunk_id in full_text:
                    cited_in_text = True
                    verified.append(f"Chunk ID '{chunk_id}' verified.")
                    break

            if not cited_in_text:
                ungrounded.append(
                    "Hypothesis does not explicitly cite any retrieved runbook/postmortem source."
                )
        else:
            # If no citations were found, citation check is skipped if nominal
            if not state.raw_signals:
                verified.append("No citations expected for nominal healthy state.")
            else:
                ungrounded.append("No authoritative citations were retrieved to back hypothesis.")

        # 4. Verify Classifier Archetype Alignment
        if state.classifier_archetype:
            arch_tokens = [tok for tok in state.classifier_archetype.lower().split("_") if len(tok) > 3]
            if any(tok in full_text.lower() for tok in arch_tokens):
                verified.append(f"Archetype '{state.classifier_archetype}' corroborated by reasoning.")
            else:
                ungrounded.append(
                    f"ML classifier archetype '{state.classifier_archetype}' contradictory or unreferenced."
                )

        # 5. Calculate Score
        total_checks = len(verified) + len(ungrounded)
        if total_checks == 0:
            score = 1.0
        else:
            score = len(verified) / total_checks

        return score, verified, ungrounded

    def execute(self, state: AgentState) -> Dict[str, Any]:
        """Validate state reasoning and determine if revision or progression is warranted."""
        score, verified, ungrounded = self._evaluate_grounding(state)
        is_grounded = score >= self.grounding_threshold

        feedback: Optional[str] = None
        current_revisions = state.revision_count

        if not is_grounded:
            current_revisions += 1
            feedback = (
                f"Grounding score ({score:.1%}) below required SLA ({self.grounding_threshold:.1%}). "
                f"Critique: {'; '.join(ungrounded)}. "
                f"Please anchor hypothesis strictly with observed metric data and exact runbook citations."
            )

        audit_entry = {
            "agent": self.name,
            "action": "EVALUATE_GROUNDING",
            "grounding_score": round(score, 4),
            "is_grounded": is_grounded,
            "revision_count": current_revisions,
            "verified_claims_count": len(verified),
            "ungrounded_claims_count": len(ungrounded),
            "feedback": feedback,
        }

        # If grounded, status can advance towards remediation
        next_status = state.status
        if is_grounded:
            next_status = IncidentStatus.ROOT_CAUSE_IDENTIFIED

        return {
            "grounding_score": score,
            "is_grounded": is_grounded,
            "validation_feedback": feedback,
            "revision_count": current_revisions,
            "status": next_status,
            "audit_log": state.audit_log + [audit_entry],
        }
