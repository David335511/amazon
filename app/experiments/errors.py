"""Error hierarchy for the experimentation platform."""


class ExperimentError(Exception):
    """Base class for all experiment engine errors."""


class ExperimentValidationError(ExperimentError):
    """Invalid input (unknown type, empty variant key, bad metric, ...)."""


class ExperimentNotFoundError(ExperimentError):
    """A requested experiment / variant / report could not be found."""


class ExperimentConflictError(ExperimentError):
    """A state transition is illegal (e.g. adding a variant to a running exp)."""
