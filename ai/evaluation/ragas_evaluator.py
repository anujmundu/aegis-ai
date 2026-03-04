"""Automated RAG & Multi-Agent Evaluation Engine (Ragas-style Reliability Evaluator).

Evaluates:
1. Faithfulness / Grounding Accuracy: Are hypothesis claims strictly derived from retrieved evidence?
2. Context Precision: Are the retrieved chunks relevant to the target failure symptoms?
3. Context Recall: Was the ground-truth authoritative SOP successfully retrieved?
4. Remediation Appropriateness: Does the proposed action match the operational SOP?
"""

import logging
from typing import Dict, List

import numpy as np
from pydantic import BaseModel, Field

from ai.agents.graph import ReliabilityGraph
from ai.agents.state import AgentState
from data.schemas.events import AnomalyArchetype, AnomalySignal, IncidentSeverity

logger = logging.getLogger("aegisai.evaluation.ragas")


# Expected ground truth SOP actions per archetype
EXPECTED_ACTIONS: Dict[str, List[str]] = {
    AnomalyArchetype.DB_CONNECTION_POOL_SATURATION.value: [
        "EXPAND_DB_CONNECTION_POOL",
        "INCREASE_POOL",
    ],
    AnomalyArchetype.MEMORY_LEAK_GC_PAUSE.value: [
        "ROLLING_CONTAINER_RESTART",
        "RESTART_PODS",
    ],
    AnomalyArchetype.CASCADING_THIRD_PARTY_FAILURE.value: [
        "ENGAGE_CIRCUIT_BREAKER",
        "ENABLE_CIRCUIT_BREAKER",
    ],
    AnomalyArchetype.PAYMENT_GATEWAY_OUTAGE.value: [
        "FAILOVER_PAYMENT_GATEWAY",
        "REROUTE_PAYMENT",
    ],
    AnomalyArchetype.BLACK_FRIDAY_TRAFFIC_BURST.value: [
        "SCALE_HORIZONTAL_POD_AUTOSCALER",
        "SCALE_OUT",
    ],
}


class RAGScenarioEvalResult(BaseModel):
    """Evaluation result for an individual incident scenario."""

    archetype: str
    service_id: str
    faithfulness_score: float
    context_precision: float
    context_recall: float
    remediation_appropriate: bool
    retrieved_citations: List[str] = Field(default_factory=list)
    proposed_action: str
    passed_rag_gate: bool


class RAGBenchmarkReport(BaseModel):
    """Aggregate benchmark report across all operational incident archetypes."""

    total_scenarios_evaluated: int
    macro_faithfulness: float
    macro_context_precision: float
    macro_context_recall: float
    action_accuracy: float
    all_gates_passed: bool
    scenario_breakdown: List[RAGScenarioEvalResult] = Field(default_factory=list)
    summary_markdown: str


class RAGEvaluator:
    """Automated evaluation suite verifying agent and RAG fidelity."""

    def __init__(
        self,
        min_faithfulness: float = 0.95,
        min_context_precision: float = 0.70,
        min_context_recall: float = 0.80,
    ) -> None:
        self.min_faithfulness = min_faithfulness
        self.min_context_precision = min_context_precision
        self.min_context_recall = min_context_recall

    def evaluate_scenario(
        self,
        archetype: AnomalyArchetype,
        state: AgentState,
    ) -> RAGScenarioEvalResult:
        """Evaluate a completed AgentState against ground truth expectations."""
        arch_val = archetype.value

        # 1. Faithfulness Score (from ValidatorAgent)
        faithfulness = float(state.grounding_score)

        # Extract archetype keyword tokens for domain grounding
        arch_keywords = [tok.lower() for tok in arch_val.split("_") if len(tok) > 3]

        # 2. Context Precision
        # Ratio of retrieved citations that relate to the domain, symptoms, runbooks, or archetype
        citations = state.citations
        relevant_chunks = 0
        citation_texts = []
        for c in citations:
            cite_str = c.get("citation", "")
            src_str = c.get("source_uri", "")
            sec_str = c.get("section", "")
            combined_ref = f"{cite_str} {src_str} {sec_str}".lower()
            citation_texts.append(cite_str)

            is_relevant = (
                any(term in combined_ref for term in ["sop", "postmortem", "runbook", "rb_", "pm_", state.service_id.lower()])
                or any(tok in combined_ref for tok in arch_keywords)
            )
            if is_relevant:
                relevant_chunks += 1

        context_precision = (relevant_chunks / len(citations)) if citations else 0.0

        # 3. Context Recall
        # Was the specific archetype keyword retrieved in at least one chunk?
        has_recall = any(
            any(tok in cite.lower() for tok in arch_keywords) for cite in citation_texts
        )
        context_recall = 1.0 if has_recall else 0.5

        # 4. Remediation Action Appropriateness
        proposed = (
            state.remediation_proposal.action_type
            if state.remediation_proposal
            else "NONE"
        )
        valid_actions = EXPECTED_ACTIONS.get(arch_val, [])
        action_ok = proposed in valid_actions

        # Pass Gate Check
        passed_gate = bool(
            faithfulness >= self.min_faithfulness
            and context_precision >= self.min_context_precision
            and context_recall >= self.min_context_recall
            and action_ok
        )

        return RAGScenarioEvalResult(
            archetype=arch_val,
            service_id=state.service_id,
            faithfulness_score=round(faithfulness, 4),
            context_precision=round(context_precision, 4),
            context_recall=round(context_recall, 4),
            remediation_appropriate=action_ok,
            retrieved_citations=citation_texts,
            proposed_action=proposed,
            passed_rag_gate=passed_gate,
        )

    def run_benchmark(self, graph: ReliabilityGraph) -> RAGBenchmarkReport:
        """Run synthetic multi-archetype benchmark through the ReliabilityGraph."""
        scenarios = [
            (
                AnomalyArchetype.DB_CONNECTION_POOL_SATURATION,
                "checkout-service",
                "db_connection_pool_active_connections",
                97.0,
                40.0,
                5.8,
            ),
            (
                AnomalyArchetype.MEMORY_LEAK_GC_PAUSE,
                "checkout-service",
                "infra_memory_percent",
                92.0,
                50.0,
                5.2,
            ),
            (
                AnomalyArchetype.CASCADING_THIRD_PARTY_FAILURE,
                "payment-service",
                "app_latency_p99_ms",
                2450.0,
                180.0,
                6.5,
            ),
            (
                AnomalyArchetype.PAYMENT_GATEWAY_OUTAGE,
                "checkout-service",
                "biz_checkout_success_rate",
                32.0,
                99.0,
                -7.2,
            ),
            (
                AnomalyArchetype.BLACK_FRIDAY_TRAFFIC_BURST,
                "order-processing",
                "app_requests_per_sec",
                3200.0,
                800.0,
                4.8,
            ),
        ]

        results: List[RAGScenarioEvalResult] = []

        for arch, svc, metric, obs, base, dev in scenarios:
            sig = AnomalySignal(
                signal_id=f"eval-{arch.value[:4]}",
                service_id=svc,
                metric_name=metric,
                detector_type="modified_z_score",
                observed_value=obs,
                baseline_value=base,
                deviation_sigma=dev,
                severity=IncidentSeverity.CRITICAL if abs(dev) > 5.0 else IncidentSeverity.HIGH,
                is_anomaly=True,
                is_primary_driver=True,
            )

            state = AgentState(
                incident_id=f"EVAL-{arch.value}",
                service_id=svc,
                severity=IncidentSeverity.CRITICAL if abs(dev) > 5.0 else IncidentSeverity.HIGH,
                raw_signals=[sig],
                classifier_archetype=arch.value,
                classifier_confidence=0.97,
            )

            final_state = graph.run(state)
            eval_res = self.evaluate_scenario(arch, final_state)
            results.append(eval_res)

        macro_faith = float(np.mean([r.faithfulness_score for r in results]))
        macro_prec = float(np.mean([r.context_precision for r in results]))
        macro_rec = float(np.mean([r.context_recall for r in results]))
        action_acc = float(np.mean([1.0 if r.remediation_appropriate else 0.0 for r in results]))
        all_passed = all(r.passed_rag_gate for r in results)

        md_lines = [
            "# Automated GenAI & RAG Reliability Benchmark Report",
            f"**Scenarios Evaluated**: {len(results)}",
            f"**All Gates Passed**: {'YES (PASSED)' if all_passed else 'NO (FAILED)'}",
            "",
            "## Summary Metrics",
            f"- **Macro Faithfulness (Grounding)**: {macro_faith:.1%} (Target: >= {self.min_faithfulness:.1%})",
            f"- **Macro Context Precision**: {macro_prec:.1%} (Target: >= {self.min_context_precision:.1%})",
            f"- **Macro Context Recall**: {macro_rec:.1%} (Target: >= {self.min_context_recall:.1%})",
            f"- **Remediation Action Accuracy**: {action_acc:.1%} (Target: 100.0%)",
            "",
            "## Scenario Breakdown",
            "| Archetype | Faithfulness | Context Precision | Context Recall | Proposed Action | Gate Status |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for r in results:
            status_badge = "PASS" if r.passed_rag_gate else "FAIL"
            md_lines.append(
                f"| `{r.archetype}` | {r.faithfulness_score:.1%} | {r.context_precision:.1%} | {r.context_recall:.1%} | `{r.proposed_action}` | {status_badge} |"
            )

        summary_md = "\n".join(md_lines)

        return RAGBenchmarkReport(
            total_scenarios_evaluated=len(results),
            macro_faithfulness=round(macro_faith, 4),
            macro_context_precision=round(macro_prec, 4),
            macro_context_recall=round(macro_rec, 4),
            action_accuracy=round(action_acc, 4),
            all_gates_passed=all_passed,
            scenario_breakdown=results,
            summary_markdown=summary_md,
        )
