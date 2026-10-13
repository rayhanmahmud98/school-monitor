from django import template

register = template.Library()

STATUS_CLASSES = {
    "PRESENT": "bg-green-100 text-green-800",
    "ABSENT": "bg-red-100 text-red-800",
    "LATE": "bg-yellow-100 text-yellow-800",
    "EXCUSED": "bg-blue-100 text-blue-800",
    "DRAFT": "bg-slate-100 text-slate-700",
    "SUBMITTED": "bg-amber-100 text-amber-800",
    "APPROVED": "bg-emerald-100 text-emerald-800",
    "NOT_STARTED": "bg-slate-100 text-slate-500",
}


@register.filter
def attr(obj, path):
    """Resolve 'a.b.c' on an object, calling methods; booleans become ✓ / —."""
    for part in str(path).split("."):
        if obj is None:
            return ""
        obj = getattr(obj, part, "")
        if callable(obj):
            obj = obj()
    if obj is True:
        return "✓"
    if obj is False:
        return "—"
    return "" if obj is None else obj


@register.filter
def startswith(text, prefix):
    return str(text).startswith(str(prefix))


@register.filter
def status_class(status):
    """Tailwind colour classes for attendance / marksheet status badges."""
    return STATUS_CLASSES.get(status, "bg-slate-100 text-slate-700")
