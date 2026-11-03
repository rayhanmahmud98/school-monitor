"""Read-only, permission-scoped queries for finance. Selectors never write."""
from accounts.models import User
from accounts.scope import parent_students
from students.models import Student

from .permissions import user_can

# Any one of these gives a user the right to look students up for finance work.
_STAFF_CODENAMES = ("enter_payment", "confirm_payment", "verify_payment",
                    "view_reports", "view_receipt", "check_slip")


def finance_students(user):
    """Students a finance-staff user may work with. Parents and teachers get none."""
    if not getattr(user, "is_authenticated", False):
        return Student.objects.none()
    if user.role == User.Role.ADMIN or any(user_can(user, c) for c in _STAFF_CODENAMES):
        return Student.objects.filter(is_active=True)
    return Student.objects.none()


def portal_students(user):
    """Students a parent may view in the finance portal (linked children only)."""
    if getattr(user, "is_authenticated", False) and user.role == User.Role.PARENT:
        return parent_students(user)
    return Student.objects.none()
