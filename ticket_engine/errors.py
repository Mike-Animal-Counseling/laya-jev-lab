"""Stable, sanitized errors suitable for an integrating application's boundary."""


class EngineError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(message)
