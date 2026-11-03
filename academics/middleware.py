import logging

from accounts.utils import client_ip

from .models import AuditLog

logger = logging.getLogger(__name__)

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# A successful form submission redirects; a 200 on POST is a re-rendered invalid form.
SUCCESS_CODES = {301, 302, 303, 204}
# Apps that write their own audit trail inside their database transaction.
SKIP_APPS = {"finance"}


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class AuditLogMiddleware:
    """Log every successful write request by an authenticated user to AuditLog.

    The log write must never turn a request that already succeeded into an
    error, so failures are logged and swallowed.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (
            request.method in WRITE_METHODS
            and response.status_code in SUCCESS_CODES
            and getattr(request.user, "is_authenticated", False)
            and not getattr(request, "_audit_logged", False)   # view already logged details
            and not request.path.startswith(("/static/", "/media/"))
        ):
            match = request.resolver_match
            if match is not None and match.app_name in SKIP_APPS:
                return response
            try:
                AuditLog.objects.create(
                    user=request.user,
                    action=f"{request.method} {match.view_name if match else request.path}",
                    target_model=match.app_name if match else "",
                    target_id=_int_or_none(match.kwargs.get("pk")) if match else None,
                    details=request.path,
                    ip_address=client_ip(request),
                )
            except Exception:  # noqa: BLE001 - audit problems must not fail the request
                logger.exception("Audit log write failed for %s", request.path)
        return response
