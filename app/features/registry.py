"""Feature registry — auto-discovery of `FeatureComputer` implementations.

The registry maps a feature key to its `FeatureComputer` class. Computers are
discovered by walking the subclasses of `FeatureComputer` (importing the
computers module to trigger registration), so adding a feature is just defining
a new computer and importing it.
"""

from __future__ import annotations

import inspect

from app.features.base import FeatureComputer


def _iter_computers():
    """Yield all non-abstract `FeatureComputer` subclasses (transitively)."""
    seen: set[type[FeatureComputer]] = set()
    stack: list[type[FeatureComputer]] = [FeatureComputer]
    while stack:
        cls = stack.pop()
        for sub in cls.__subclasses__():
            if sub in seen:
                continue
            seen.add(sub)
            stack.append(sub)
            if not inspect.isabstract(sub):
                yield sub


def feature_registry() -> dict[str, type[FeatureComputer]]:
    """Return {feature_key -> FeatureComputer} for all registered features."""
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is None:
        from app.features import computers

        computers.register_computers()
        _REGISTRY_CACHE = {cls.key: cls for cls in _iter_computers() if cls.key}
    return _REGISTRY_CACHE


_REGISTRY_CACHE: dict[str, type[FeatureComputer]] | None = None


def get_feature_computer(feature_key: str) -> type[FeatureComputer] | None:
    """Return the computer class for a feature key, or None if unknown."""
    return feature_registry().get(feature_key)
