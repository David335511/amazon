"""Feature engineering platform.

Every computed metric is stored **once** and **reused** (a feature store). A
feature value row records the metric plus its audit trail: **calculation
method, timestamp, confidence, version, and lineage** (the exact input signals
and versions that produced it). Features are versioned and refreshable; a
computed value is served from the store until it goes stale, at which point it
is recomputed.

Design pillars:
- **Compute once, reuse**: the latest value per (feature, entity) is persisted
  and returned until `computed_at + ttl` passes.
- **Pluggable computers**: each feature is a `FeatureComputer` declaring its
  key, formula, version, value type, required signals and refresh TTL. New
  features (including future ML models) are added by registering a new computer.
- **Signals as a seam**: computers read typed input signals via `SignalProvider`
  (default: local). ML models can plug in as either a signal provider or a
  computer.
- **Full provenance**: every stored value carries version + lineage so any
  downstream decision is auditable and reproducible.
"""

from app.features.base import (
    EntityContext,
    FeatureComputer,
    FeatureComputeResult,
)
from app.features.config import FeatureConfig
from app.features.errors import (
    FeatureError,
    FeatureNotCalculatedError,
    FeatureNotFoundError,
    FeatureValidationError,
)
from app.features.lineage import build_lineage
from app.features.manager import FeatureManager
from app.features.models import FeatureValue, FeatureValueType
from app.features.registry import feature_registry, get_feature_computer
from app.features.repository import FeatureRepository
from app.features.schemas import (
    FeatureBatchItem,
    FeatureBatchRequest,
    FeatureCalculateRequest,
    FeatureCapabilities,
    FeatureDefinitionRead,
    FeatureStats,
    FeatureValueList,
    FeatureValueRead,
)
from app.features.signals import (
    SignalBundle,
    SignalInfo,
    SignalProvider,
    build_signal_provider,
    build_signals,
)

__all__ = [
    "EntityContext",
    "FeatureBatchItem",
    "FeatureBatchRequest",
    "FeatureCalculateRequest",
    "FeatureCapabilities",
    "FeatureComputeResult",
    "FeatureComputer",
    "FeatureConfig",
    "FeatureDefinitionRead",
    "FeatureError",
    "FeatureManager",
    "FeatureNotCalculatedError",
    "FeatureNotFoundError",
    "FeatureRepository",
    "FeatureStats",
    "FeatureValidationError",
    "FeatureValue",
    "FeatureValueList",
    "FeatureValueRead",
    "FeatureValueType",
    "SignalBundle",
    "SignalInfo",
    "SignalProvider",
    "build_lineage",
    "build_signal_provider",
    "build_signals",
    "feature_registry",
    "get_feature_computer",
]
