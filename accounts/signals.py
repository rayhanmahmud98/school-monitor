"""Signal handlers for the accounts app.

Connected in accounts/apps.py -> ready(). Kept in its own module so it isn't
imported implicitly at app-load time (which can cause circular imports).
"""
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .models import LoginHistory


def _client_ip(request):
    """Return the caller's IP, honouring X-Forwarded-For if present."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


@receiver(user_logged_in)
def record_login(sender, request, user, **kwargs):
    """Write one LoginHistory row per successful login."""
    LoginHistory.objects.create(
        user=user,
        ip_address=_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
        session_key=request.session.session_key or "",
    )