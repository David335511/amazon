"""Exception hierarchy for the feature engineering platform."""

from __future__ import annotations


class FeatureError(Exception):
    """Base class for all feature-engineering errors."""


class FeatureNotFoundError(FeatureError):
    """Raised when no stored value exists for a (feature, entity)."""

    def __init__(self, feature_key: str, entity_type: str, entity_id: str) -> None:
        self.feature_key = feature_key
        self.entity_type = entity_type
        self.entity_id = entity_id
        super().__init__(
            f"No stored feature value for {feature_key!r} on {entity_type}/{entity_id}"
        )


class FeatureValidationError(FeatureError):
    """Raised when a calculation request is malformed."""


class FeatureNotCalculatedError(FeatureError):
    """Raised when a feature computer could not produce a value."""
