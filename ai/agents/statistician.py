"""Statistician Agent Node for AegisAI Multi-Agent Reliability Graph.

Role:
- Analyzes raw anomaly signals across all architectural tiers.
- Ranks metric deviations and isolates the primary driver.
- Identifies cross-tier correlation patterns and computes quantitative statistical summary.
"""

from typing import Any, Dict

from ai.agents.state import AgentState
from data.schemas.events import IncidentStatus


class StatisticianAgent:
    """Specialized agent node performing quantitative telemetry triage."""

    def __init__(self, name: str = "statistician") -> None:
        self.name = name

    def execute(self, state: AgentState) -> Dict[str, Any]:
        """Process anomaly signals and isolate the primary driver metric."""
        signals = state.raw_signals
        if not signals:
            return {
                "statistical_summary": "No active anomaly signals detected; telemetry nominal.",
                "status": IncidentStatus.RESOLVED,
                "audit_log": state.audit_log + [{
                    "agent": self.name,
                    "action": "TRIAGE",
                    "result": "No anomaly signals found.",
                }],
            }

        # 1. Isolate Primary Driver
        # First check if any signal is explicitly marked is_primary_driver
        primary = next((s for s in signals if s.is_primary_driver), None)
        if primary is None:
            # Fall back to signal with largest absolute deviation sigma
            primary = max(signals, key=lambda s: abs(s.deviation_sigma))

        # 2. Group Correlated Signals
        signal_names = list({s.metric_name for s in signals})
        tier_breakdown: Dict[str, list] = {"infra": [], "app": [], "db": [], "biz": []}

        for s in signals:
            name = s.metric_name
            if name.startswith("infra_"):
                tier_breakdown["infra"].append(f"{name} ({s.deviation_sigma:+.1f}σ)")
            elif name.startswith("app_"):
                tier_breakdown["app"].append(f"{name} ({s.deviation_sigma:+.1f}σ)")
            elif name.startswith("db_"):
                tier_breakdown["db"].append(f"{name} ({s.deviation_sigma:+.1f}σ)")
            elif name.startswith("biz_"):
                tier_breakdown["biz"].append(f"{name} ({s.deviation_sigma:+.1f}σ)")

        # 3. Format Quantitative Statistical Summary
        summary_lines = [
            f"PRIMARY DRIVER: '{primary.metric_name}' ({primary.detector_type}) with deviation of {primary.deviation_sigma:+.1f}σ.",
            f"  Observed: {primary.observed_value} vs Baseline: {primary.baseline_value}.",
            "CORRELATED MULTI-TIER IMPACT:",
        ]
        for tier, sigs in tier_breakdown.items():
            if sigs:
                summary_lines.append(f"  - {tier.upper()} Tier: {', '.join(sigs)}")

        summary_text = "\n".join(summary_lines)

        audit_entry = {
            "agent": self.name,
            "action": "QUANTITATIVE_TRIAGE",
            "primary_driver": primary.metric_name,
            "max_sigma": primary.deviation_sigma,
            "correlated_signals_count": len(signals),
        }

        return {
            "primary_driver": primary,
            "correlated_signal_names": signal_names,
            "statistical_summary": summary_text,
            "status": IncidentStatus.INVESTIGATING,
            "audit_log": state.audit_log + [audit_entry],
        }
