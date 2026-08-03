"""Error hierarchy for the forecasting platform."""


class ForecastError(Exception):
    """Base class for all forecasting errors."""


class ForecastValidationError(ForecastError):
    """Invalid request (unknown model/target, horizon over limit, empty series)."""


class ForecastNotFoundError(ForecastError):
    """A stored forecast / actual could not be found."""


class ForecastUnavailableError(ForecastError):
    """A requested model is not available in this deployment.

    e.g. an ML model whose backend (sklearn) is not installed.
    """

    def __init__(self, model_name: str, reason: str = "") -> None:
        self.model_name = model_name
        detail = f"Forecasting model {model_name!r} is not available"
        if reason:
            detail += f": {reason}"
        super().__init__(detail)
