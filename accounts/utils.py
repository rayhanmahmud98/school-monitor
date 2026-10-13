"""Small helpers shared across the accounts app and its CRUD factory."""
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator


def paginate(request, queryset, per_page=25):
    """Paginate a queryset using the `page` query parameter."""
    paginator = Paginator(queryset, per_page)
    page_number = request.GET.get("page", 1)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    params = request.GET.copy()
    params.pop("page", None)
    querystring = params.urlencode()
    return page_obj, querystring


def client_ip(request):
    """Return the caller's IP, honouring X-Forwarded-For if present."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
