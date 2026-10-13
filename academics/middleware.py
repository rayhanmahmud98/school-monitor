from accounts.utils import client_ip

from .models import AuditLog

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# A successful form submission redirects; a 200 on POST is a re-rendered invalid form.
SUCCESS_CODES = {301, 302, 303, 204}


class AuditLogMiddleware:
    """Log every successful write request by an authenticated user to AuditLog."""

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
            AuditLog.objects.create(
                user=request.user,
                action=f"{request.method} {match.view_name if match else request.path}",
                target_model=match.app_name if match else "",
                target_id=(match.kwargs.get("pk") if match else None),
                details=request.path,
                ip_address=client_ip(request),
            )
        return response
