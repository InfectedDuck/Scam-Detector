"""Typed failures.

Every one of these is something a caller might reasonably handle differently:
a missing key is a deployment problem, a transient 5xx is worth retrying, and
a schema violation after a repair attempt means the model cannot produce the
shape we need and the verdict must fall back rather than guess.
"""

from __future__ import annotations


class LLMError(Exception):
    """Base for everything this package raises."""


class UnknownProvider(LLMError):
    """The model name matches no provider routing rule."""


class ProviderNotConfigured(LLMError):
    """The provider was resolved but its API key is absent from the environment."""


class TransientError(LLMError):
    """A 429, a 5xx, or a connection failure. Retryable with backoff."""


class SchemaViolation(LLMError):
    """The model produced output that does not validate, twice.

    Raised rather than returning a partial object. A half-parsed judgement is
    worse than no judgement: the fusion stage would treat missing fields as
    zero confidence and silently shift the band.
    """


class OfflineCacheMiss(LLMError):
    """SAQBOL_LLM_OFFLINE is set and the call is not in the cassette.

    This is the mechanism that keeps CI honest. If a test drifts into making a
    real call, it fails loudly here instead of quietly costing money or hanging
    on a network that CI does not have.
    """
