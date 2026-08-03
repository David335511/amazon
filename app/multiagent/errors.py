"""Exception hierarchy for the multi-agent orchestration framework."""

from __future__ import annotations


class MultiAgentError(Exception):
    """Base class for all multi-agent errors."""


class AgentNotFoundError(MultiAgentError):
    """Raised when a requested agent role is not registered."""


class ToolNotFoundError(MultiAgentError):
    """Raised when a requested tool is not registered."""


class AgentExecutionError(MultiAgentError):
    """Raised when an agent fails during execution."""


class PipelineError(MultiAgentError):
    """Raised when a pipeline cannot be constructed or run."""
