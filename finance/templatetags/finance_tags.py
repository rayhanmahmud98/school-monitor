from django import template

from ..permissions import user_can

register = template.Library()


@register.filter
def can(user, codename):
    """{% if request.user|can:'view_audit' %} ... {% endif %}"""
    return user_can(user, codename)
