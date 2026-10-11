"""Standard API error envelope: {"error": {"code", "message", "details"}}.

Unexpected exceptions are logged server-side and returned as a generic 500,
so stack traces, SQL and secret-bearing values never reach the client.
"""

import logging

from django.db import IntegrityError
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


def _error(code: str, message: str, http_status: int, details=None, headers=None) -> Response:
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return Response(body, status=http_status, headers=headers)


def api_exception_handler(exc, context):
    if isinstance(exc, ServiceError):
        return _error(exc.error_code, str(exc.detail), exc.status_code, details=exc.details)
    if isinstance(exc, ProtectedError):
        return _error("conflict", "This record is still in use and cannot be deleted.", status.HTTP_409_CONFLICT)
    if isinstance(exc, IntegrityError):
        logger.warning("Integrity error in %s", context.get("view").__class__.__name__)
        return _error("conflict", "The request conflicts with existing data.", status.HTTP_409_CONFLICT)

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
