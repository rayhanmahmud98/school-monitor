"""
Finance permission checks.

Rules:
* Admin-role users hold every finance permission, EXCEPT the codenames in
  PRIMARY_ADMIN_ONLY, which need the primary admin account.
* Every other role needs the Django permission `finance.<codename>`, granted
  through role groups (created when the finance models exist).
* Deny by default: teachers and parents hold no finance permissions.

Object-level scoping (which students a user may see) lives in selectors.py.
"""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from accounts.models import User

PRIMARY_ADMIN_ONLY = frozenset({"reopen_period", "override_slip"})


def user_can(user, codename):
    """True if `user` may perform the finance action `codename`."""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    if user.role == User.Role.ADMIN:
        if codename in PRIMARY_ADMIN_ONLY:
            return user.is_primary_admin
        return True
    return user.has_perm(f"finance.{codename}")


def finance_permission_required(codename):
    """Function-view decorator: anonymous -> login page; lacking permission -> 403."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not user_can(request.user, codename):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


class FinancePermissionMixin:
    """Class-based-view equivalent. Set `required_permission` to a codename."""

    required_permission = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not self.required_permission or not user_can(request.user, self.required_permission):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
