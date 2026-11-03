"""Create the finance permission groups and keep users in the right one."""
from django.contrib.auth.models import Group, Permission

from ..constants import FINANCE_ROLES, GROUPS, ROLE_TO_GROUP


def sync_groups():
    """Idempotent: make each group hold exactly its configured permissions."""
    perms = {p.codename: p for p in Permission.objects.filter(content_type__app_label="finance")}
    for group_name, codenames in GROUPS.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        wanted = [perms[c] for c in codenames if c in perms]
        group.permissions.set(wanted)


def sync_user(user):
    """Put a user of a finance role in that role's group (and only that one)."""
    target_name = ROLE_TO_GROUP.get(user.role) if user.role in FINANCE_ROLES else None
    current = user.groups.filter(name__in=list(GROUPS))
    for group in current:
        if group.name != target_name:
            user.groups.remove(group)
    if target_name and not current.filter(name=target_name).exists():
        group, _ = Group.objects.get_or_create(name=target_name)
        user.groups.add(group)
