from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("admin/", views.admin_dashboard, name="admin"),
    path("teacher/", views.teacher_dashboard, name="teacher"),
    path("parent/", views.parent_dashboard, name="parent"),
    
    # Public ID Verification
    path("verify/id/<uuid:token>/", views.verify_id_card, name="verify_id_card"),
]