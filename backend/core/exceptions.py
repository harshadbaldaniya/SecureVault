"""Standard API error envelope: {"error": {"code", "message", "details"}}.

Unexpected exceptions are logged server-side and returned as a generic 500,
so stack traces, SQL and secret-bearing values never reach the client. A database or Redis that cannot be
reached (or a transient lock failure) is a 503 with Retry-After, never a 500 and never a message naming the host.
"""

import logging

import redis
from django.db import IntegrityError, InterfaceError, OperationalError
from django.db.models import ProtectedError
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


class ServiceError(exceptions.APIException):
    """A business-rule violation raised by a service function (default 400)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "invalid"

    def __init__(self, message: str, code: str = "invalid", *, details=None, status_code: int | None = None):
        super().__init__(detail=message, code=code)
        self.error_code = code
        self.details = details
        if status_code is not None:
            self.status_code = status_code


# Failures of the services we depend on. Transient by nature, so the client is told to retry.
UNAVAILABLE = (OperationalError, InterfaceError, redis.exceptions.RedisError)
UNAVAILABLE_MESSAGE = "This service is temporarily unavailable. Please try again in a moment."
RETRY_AFTER_SECONDS = "5"


class ServiceUnavailable(ServiceError):
    """A dependency this request needs is not available (503)."""

    def __init__(self, message: str = UNAVAILABLE_MESSAGE):
        super().__init__(message, "service_unavailable", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


def _error(code: str, message: str, http_status: int, details=None, headers=None) -> Response:
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return Response(body, status=http_status, headers=headers)


def api_exception_handler(exc, context):
    if isinstance(exc, ServiceError):
        headers = (
            {"Retry-After": RETRY_AFTER_SECONDS} if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE else None
        )
        return _error(exc.error_code, str(exc.detail), exc.status_code, details=exc.details, headers=headers)
    if isinstance(exc, ProtectedError):
        return _error("conflict", "This record is still in use and cannot be deleted.", status.HTTP_409_CONFLICT)
    if isinstance(exc, IntegrityError):
        logger.warning("Integrity error in %s", context.get("view").__class__.__name__)
        return _error("conflict", "The request conflicts with existing data.", status.HTTP_409_CONFLICT)

    if isinstance(exc, UNAVAILABLE):
        logger.error(
            "A dependency was unavailable in %s (%s)", context.get("view").__class__.__name__, type(exc).__name__
        )
        return _error(
            "service_unavailable",
            UNAVAILABLE_MESSAGE,
            status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"Retry-After": RETRY_AFTER_SECONDS},
        )

    response = exception_handler(exc, context)
    if response is None:
        logger.exception("Unhandled API exception", exc_info=exc)
        return _error("server_error", "Internal server error.", status.HTTP_500_INTERNAL_SERVER_ERROR)

    headers = {k: v for k, v in response.headers.items() if k in {"WWW-Authenticate", "Retry-After"}}
    if isinstance(exc, exceptions.ValidationError):
        return _error("invalid", "Invalid input.", response.status_code, details=response.data, headers=headers)

    data = response.data if isinstance(response.data, dict) else {}
    message = str(data.get("detail", "Request failed."))
    code = getattr(getattr(exc, "detail", None), "code", None) or getattr(exc, "default_code", "error")
    return _error(str(code), message, response.status_code, headers=headers)
