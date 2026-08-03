"""Signal acquisition for feature computers.

A `SignalBundle` is the typed input a `FeatureComputer` consumes. Each signal
carries a value plus provenance (``source`` and ``version``) so the lineage of
a computed feature is fully auditable â€” a computer can record exactly which
signals it used and at what version.

`SignalProvider` is the seam for where signals come from. The default `local`
provider wraps caller-provided data (or neutral defaults); future providers
(e.g. querying the product/revenue repositories, a feature-server, or a remote
ML service) implement the same interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel

from app.features.config import FeatureConfig

if TYPE_CHECKING:
    from app.features.base import EntityContext


class SignalInfo(BaseModel):
    """A single input signal with provenance."""

    value: Any = None
    source: str = "unknown"  # e.g. "product_repository", "supplier_profile", "default"
    version: str = "1.0.0"


class SignalBundle:
    """Ordered mapping of signal name -> SignalInfo.

    A computer reads raw values via ``.get(name)`` and checks real availability
    via ``.available(name)``. Signals that were *not* provided are simply absent
    (``available()`` returns False), so computers can degrade gracefully and
    report lower confidence instead of guessing.
    """

    __slots__ = ("_signals",)

    def __init__(self, signals: Mapping[str, SignalInfo] | None = None) -> None:
        self._signals = dict(signals or {})

    def get(self, key: str, default: Any = None) -> Any:
        """Return the raw signal value, or `default` if absent."""
        info = self._signals.get(key)
        return info.value if info is not None else default

    def available(self, key: str) -> bool:
        """Whether a real (non-defaulted) signal value was provided."""
        return key in self._signals

    def info(self, key: str) -> SignalInfo | None:
        """Return the `SignalInfo` for a signal, or None if absent."""
        return self._signals.get(key)

    def keys(self) -> list[str]:
        return list(self._signals.keys())

    def as_dict(self) -> dict[str, Any]:
        """Raw value map (no provenance)."""
        return {k: v.value for k, v in self._signals.items()}

    def lineage(self) -> list[dict[str, Any]]:
        """Provenance records ready for a lineage payload."""
        return [
            {
                "key": k,
                "value": v.value,
                "source": v.source,
                "version": v.version,
            }
            for k, v in self._signals.items()
        ]


def build_signals(
    data: Mapping[str, Any],
    *,
    source: str = "manual",
    version: str = "1.0.0",
) -> SignalBundle:
    """Wrap a plain value dict into a `SignalBundle` with provenance."""
    return SignalBundle(
        {
            key: SignalInfo(value=value, source=source, version=version)
            for key, value in data.items()
        }
    )


def signal_confidence(signals: SignalBundle, required: tuple[str, ...]) -> float:
    """Confidence from what fraction of required signals were actually provided."""
    if not required:
        return 1.0
    available = sum(1 for key in required if signals.available(key))
    if available == 0:
        return 0.05
    return round(available / len(required), 4)


class SignalProvider(ABC):
    """Interface for acquiring the input signals a feature needs."""

    name: ClassVar[str] = "signal_provider"

    @abstractmethod
    async def fetch_signals(self, _entity: EntityContext) -> SignalBundle:
        """Fetch the signal bundle for an entity."""


class LocalSignalProvider(SignalProvider):
    """Default provider: wraps caller-supplied (or empty) signal data.

    Used directly in tests and by callers that already have their signals in
    hand. Production integrations subclass `SignalProvider` to source signals
    from the platform's repositories.
    """

    name = "local"

    def __init__(
        self,
        data: Mapping[str, Any] | None = None,
        *,
        source: str = "local",
        version: str = "1.0.0",
    ) -> None:
        self._data = dict(data or {})
        self._source = source
        self._version = version

    async def fetch_signals(self, _entity: EntityContext) -> SignalBundle:
        return build_signals(self._data, source=self._source, version=self._version)


def build_signal_provider(config: FeatureConfig) -> SignalProvider:
    """Factory for the configured `SignalProvider`.

    Currently only the always-available `local` provider exists; richer
    providers (database/HTTP/feature-server) are added here behind the same
    interface, matching the pattern used by the OCR/vision providers.
    """
    name = (config.signal_provider or "local").lower()
    if name == "local":
        return LocalSignalProvider()
    return LocalSignalProvider()  # safe fallback; no real provider configured
