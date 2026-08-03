"""Domain errors for the continuous-learning platform."""

from __future__ import annotations


class LearningError(Exception):
    """Base class for continuous-learning platform errors."""


class LearningValidationError(LearningError):
    """A request or state violated a rule (422)."""


class LearningNotFoundError(LearningError):
    """A requested entity does not exist (404)."""


class LearningConflictError(LearningError):
    """An operation conflicted with the current state (409)."""
