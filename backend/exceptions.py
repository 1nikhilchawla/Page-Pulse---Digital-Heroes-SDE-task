"""
Custom exceptions for the Page Pulse audit pipeline.

Every failure mode the auditor can hit gets its own exception class so the
API layer can translate it into a specific, sensible HTTP status + JSON body
instead of leaking a stack trace or a generic 500. See main.py's exception
handlers for the mapping.
"""


class PagePulseError(Exception):
    """Base class for all audit errors. Carries a machine-readable `code`
    (stable, for clients/tests to branch on) and a human-readable `message`.
    """

    code = "internal_error"
    status_code = 500

    def __init__(self, message: str, details: dict | None = None):
        self.message = message
        self.details = details or {}
        super().__init__(message)


class InvalidURLError(PagePulseError):
    """The submitted string isn't a usable http(s) URL."""

    code = "invalid_url"
    status_code = 400


class BlockedURLError(PagePulseError):
    """The URL resolves to a private/loopback/link-local address.

    We refuse to fetch these to avoid turning the audit endpoint into an
    open SSRF proxy against internal infrastructure (e.g. a caller passing
    http://169.254.169.254/ or http://localhost:6379/).
    """

    code = "blocked_url"
    status_code = 400


class FetchTimeoutError(PagePulseError):
    """The target server didn't respond within our timeout budget."""

    code = "timeout"
    status_code = 504


class FetchConnectionError(PagePulseError):
    """DNS failure, connection refused, TLS failure, etc."""

    code = "connection_failed"
    status_code = 502


class TooManyRedirectsError(PagePulseError):
    """The URL redirect-loops or chains past our configured limit."""

    code = "too_many_redirects"
    status_code = 502


class ResponseTooLargeError(PagePulseError):
    """The response body exceeded the size cap before we finished reading it."""

    code = "response_too_large"
    status_code = 413
