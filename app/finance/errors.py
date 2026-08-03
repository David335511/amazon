"""Error hierarchy for the financial optimization engine."""


class FinanceError(Exception):
    """Base class for all financial engine errors."""


class FinanceValidationError(FinanceError):
    """Invalid input (negative amount, unknown policy, bad opportunity)."""


class FinanceNotFoundError(FinanceError):
    """A requested financial record could not be found."""
