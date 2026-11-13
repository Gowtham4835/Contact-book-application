import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        logger.error(
            "Unhandled exception in contact-book API",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return Response(
            {
                "success": False,
                "error": "internal_server_error",
                "detail": "An unexpected error occurred. Please try again later.",
                "status": status.HTTP_500_INTERNAL_SERVER_ERROR,
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    status_code = response.status_code
    if status_code == status.HTTP_400_BAD_REQUEST:
        error = "validation_error"
    elif status_code == status.HTTP_401_UNAUTHORIZED:
        error = "authentication_required"
    elif status_code == status.HTTP_403_FORBIDDEN:
        error = "permission_denied"
    elif status_code == status.HTTP_404_NOT_FOUND:
        error = "not_found"
    elif status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        error = "rate_limited"
    else:
        error = "request_failed"

    response.data = {
        "success": False,
        "error": error,
        "detail": response.data,
        "status": status_code,
    }
    return response