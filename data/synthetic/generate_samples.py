"""CLI Utility to generate sample multi-tier telemetry datasets.

Generates:
1. data/raw/sample_telemetry.csv (Flattened tabular representation)
2. data/raw/sample_incident_scenarios.jsonl (Full Pydantic JSON snapshots)
"""

import json
from pathlib import Path

from data.schemas.events import AnomalyArchetype
from data.synthetic.telemetry_generator import MultiTierTelemetryGenerator


def generate_sample_datasets(output_dir: Path) -> None:
    """Generate both nominal and all 5 incident archetypes."""
    output_dir.mkdir(parents=True, exist_ok=True)
    generator = MultiTierTelemetryGenerator(seed=42)

    all_snapshots = []

    # 1. 120 Ticks of Nominal Baseline
    print("Generating nominal baseline...")
    generator.reset()
    nominal_snaps = generator.generate_batch(num_snapshots=120, archetype=AnomalyArchetype.NOMINAL)
    all_snapshots.extend(nominal_snaps)

    # 2. Scenarios for each Anomaly Archetype
    archetypes = [
        AnomalyArchetype.DB_CONNECTION_POOL_SATURATION,
        AnomalyArchetype.MEMORY_LEAK_GC_PAUSE,
        AnomalyArchetype.CASCADING_THIRD_PARTY_FAILURE,
        AnomalyArchetype.PAYMENT_GATEWAY_OUTAGE,
        AnomalyArchetype.BLACK_FRIDAY_TRAFFIC_BURST,
    ]

    for arch in archetypes:
        print(f"Generating incident scenario: {arch.value}...")
        scenario = generator.generate_incident_scenario(
            archetype=arch,
            total_ticks=60,
            anomaly_start_tick=20,
            anomaly_duration_ticks=25,
        )
        all_snapshots.extend(scenario)

    # Export to JSON Lines
    jsonl_path = output_dir / "sample_incident_scenarios.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for snap in all_snapshots:
            f.write(json.dumps(snap.model_dump(mode="json")) + "\n")
    print(f"Saved {len(all_snapshots)} snapshots to {jsonl_path}")

    # Export to Flattened CSV
    df = MultiTierTelemetryGenerator.to_dataframe(all_snapshots)
    csv_path = output_dir / "sample_telemetry.csv"
    df.to_csv(csv_path, index=False)
    print(f"Saved tabular dataset ({len(df)} rows, {len(df.columns)} columns) to {csv_path}")


if __name__ == "__main__":
    raw_dir = Path(__file__).resolve().parent.parent / "raw"
    generate_sample_datasets(raw_dir)
