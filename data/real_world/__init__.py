"""AegisAI Real-World Production Datasets Module.

Provides loaders, adapters, and benchmark pipelines for real-world SRE telemetry:
- Numenta Anomaly Benchmark (NAB): Real AWS CloudWatch metrics (EC2, RDS, ELB, ASG)
- Server Machine Dataset (SMD): Real 38-channel enterprise server machine telemetry
"""

from data.real_world.loader import RealWorldDataLoader, RealWorldDatasetTier

__all__ = ["RealWorldDataLoader", "RealWorldDatasetTier"]
