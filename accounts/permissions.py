"""Role-based access helpers. Every protected view must use one of these."""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from .models import User

ADMIN = User.Role.ADMIN
TEACHER = User.Role.TEACHER
PARENT = User.Role.PARENT


def role_required(*roles):
    """Function-view decorator. Anonymous -> login page; wrong role -> HTTP 403."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if request.user.role not in roles:
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


class RoleBasedAccessMixin:
    """Class-based-view equivalent of role_required. Set `allowed_roles`."""

    allowed_roles = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if self.allowed_roles and request.user.role not in self.allowed_roles:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
