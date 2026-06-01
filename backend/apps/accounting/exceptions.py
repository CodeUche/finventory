"""Custom exceptions for the accounting module."""


class GLAccountNotConfigured(Exception):
    """Raised when a required GL account mapping is missing."""

    def __init__(self, role: str):
        self.role = role
        super().__init__(f"GL account not configured for role: {role}")


class PeriodLockedError(Exception):
    """Raised when attempting to post to a locked financial period."""

    def __init__(self, message: str = ""):
        super().__init__(message or "Cannot post to a locked financial period.")
