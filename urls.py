from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from accounts.views import RoleLoginView

urlpatterns = [
    # Root URL: shows the login page for anonymous users;
    # redirects logged-in users to their role dashboard via LOGIN_REDIRECT_URL.
    path("", RoleLoginView.as_view(), name="root_login"),

    path("dashboard/", include("dashboard.urls")),
    path("accounts/", include("accounts.urls")),
    path("students/", include("students.urls")),
    path("academics/", include("academics.urls")),
    path("django-admin/", admin.site.urls),
]

# Serve uploaded media in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)