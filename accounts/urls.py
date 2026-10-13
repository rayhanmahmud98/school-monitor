from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.RoleLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("login-history/", views.login_history, name="login_history"),

    *views.users.urls,
    *views.links.urls,
]
