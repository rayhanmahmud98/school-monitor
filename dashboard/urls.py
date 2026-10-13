from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/admin/", views.admin_dashboard, name="admin"),
    path("dashboard/teacher/", views.teacher_dashboard, name="teacher"),
    path("dashboard/parent/", views.parent_dashboard, name="parent"),
]
