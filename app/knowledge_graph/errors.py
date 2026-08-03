"""Errors for the commerce knowledge graph module."""

from __future__ import annotations


class KnowledgeGraphError(Exception):
    """Base error for the knowledge graph module."""


class KnowledgeGraphNotFoundError(KnowledgeGraphError):
    """Raised when a node/edge/entity cannot be found."""


class KnowledgeGraphValidationError(KnowledgeGraphError):
    """Raised when input is invalid (missing key, bad relationship, ...)."""


class KnowledgeGraphConflictError(KnowledgeGraphError):
    """Raised when a duplicate/conflicting entity would be created."""
