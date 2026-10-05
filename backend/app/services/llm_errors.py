"""Provider error translation kept separate from task retry policy."""

from typing import Any

import httpx
import requests
from google.auth.exceptions import TransportError
from google.genai import errors as genai_errors


class LLMError(Exception):
    """Base class for expected AI-provider failures."""


class TransientLLMError(LLMError):
    """A temporary failure for which a later attempt may succeed."""


class PermanentLLMError(LLMError):
    """A provider rejection that should fail without retrying."""


_NETWORK_ERRORS = (
    TimeoutError,
    ConnectionError,
    httpx.TimeoutException,
    httpx.NetworkError,
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    TransportError,
)


def classify_provider_exception(exc: Exception) -> Exception:
    """Translate known transport/API failures without hiding programming errors.

    The installed Google Gen AI SDK exposes ``ClientError`` (4xx) and
    ``ServerError`` (5xx), both derived from ``APIError``. Only rate limiting,
    request timeout, server errors, and transport failures are transient.
    Validation and arbitrary Python exceptions are intentionally returned
    unchanged and are therefore non-retryable by Celery tasks.
    """
    if isinstance(exc, _NETWORK_ERRORS):
        return TransientLLMError(f"temporary AI provider transport failure: {type(exc).__name__}")

    if isinstance(exc, genai_errors.APIError):
        code = int(exc.code or 0)
        if code in {408, 429} or 500 <= code < 600:
            return TransientLLMError(f"temporary AI provider HTTP {code}")
        if 400 <= code < 500:
            return PermanentLLMError(f"AI provider rejected the request with HTTP {code}")

    return exc


def raise_classified_provider_exception(exc: Exception) -> Any:
    classified = classify_provider_exception(exc)
    if classified is exc:
        raise exc
    raise classified from exc
