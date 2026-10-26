from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.RoleLoginView.as_view(), name="login"),
    
    # Use the custom logout view
    path("logout/", views.custom_logout, name="logout"),
    
    path("login-history/", views.login_history, name="login_history"),

    *views.users.urls,

    path("teachers/new/", views.TeacherCreateView.as_view(), name="teacher_create"),
    path("teachers/<int:pk>/edit/", views.TeacherUpdateView.as_view(), name="teacher_update"),
    
    path("teachers/<int:pk>/", views.teacher_profile, name="teacher_profile"),
    path("teachers/<int:pk>/id-card.pdf", views.teacher_id_card, name="teacher_id_card"),

    *views.teachers.urls,
    *views.links.urls,
]