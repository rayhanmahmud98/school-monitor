from accounts.utils import client_ip

from .models import AuditLog


def log_action(request, action, target=None, details=""):
    """Write a detailed audit entry; stops the middleware adding a generic duplicate."""
    AuditLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        action=action,
        target_model=target.__class__.__name__ if target is not None else "",
        target_id=getattr(target, "pk", None),
        details=details,
        ip_address=client_ip(request),
    )
    request._audit_logged = True
