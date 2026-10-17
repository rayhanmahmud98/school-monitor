from django.contrib.auth.views import LoginView
from django.shortcuts import render
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView

from students.models import ParentStudentLink

from .crud import build_crud
from .forms import LoginForm, ParentStudentLinkForm, TeacherForm, UserAdminForm
from .models import LoginHistory, User
from .permissions import ADMIN, RoleBasedAccessMixin, role_required
from .utils import paginate


class RoleLoginView(LoginView):
    """Login page. On success LOGIN_REDIRECT_URL -> dashboard:home -> role dashboard."""
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


# Users CRUD (admin only).
# - No admin can delete themselves.
# - Nobody can delete the primary admin.
users = build_crud(
    ns="accounts", name="user", slug="users", model_class=User, form_cls=UserAdminForm,
    title="Users", singular="User",
    columns=[("Username", "username"), ("Name", "display_name"), ("Email", "email"),
             ("Role", "get_role_display"), ("Active", "is_active")],
    search_fields=("username", "first_name", "last_name", "email"),
    ordering=("role", "username"),
    can_delete=lambda obj, request: (
        obj.pk != request.user.pk and not obj.is_primary_admin
    ),
)


# Custom Views for Teachers to use TeacherForm
class TeacherCreateView(RoleBasedAccessMixin, CreateView):
    allowed_roles = (User.Role.ADMIN,)
    model = User
    form_class = TeacherForm
    template_name = "crud/form.html"
    success_url = reverse_lazy("accounts:teacher_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(title="Add Teacher", cancel_url=reverse_lazy("accounts:teacher_list"))
        return ctx


class TeacherUpdateView(RoleBasedAccessMixin, UpdateView):
    allowed_roles = (User.Role.ADMIN,)
    model = User
    form_class = TeacherForm
    template_name = "crud/form.html"
    success_url = reverse_lazy("accounts:teacher_list")

    def get_queryset(self):
        return User.objects.filter(role="TEACHER")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(title="Edit Teacher", cancel_url=reverse_lazy("accounts:teacher_list"))
        return ctx


# Teachers CRUD
teachers = build_crud(
    ns="accounts", name="teacher", slug="teachers", model_class=User, form_cls=TeacherForm,
    title="Teachers", singular="Teacher",
    columns=[("Username", "username"), ("Name", "display_name"), ("Email", "email"),
             ("Phone", "teacher_profile.phone"),
             ("Designation", "teacher_profile.designation"),
             ("Specialization", "teacher_profile.subject_specialization"),
             ("Active", "is_active")],
    search_fields=("username", "first_name", "last_name", "email",
                   "teacher_profile__phone", "teacher_profile__designation",
                   "teacher_profile__subject_specialization"),
    select_related=("teacher_profile",),
    ordering=("first_name", "last_name"),
    allow_create=True,
    allow_delete=False,
    base_queryset=User.objects.filter(role="TEACHER"),
)

# Parent links
links = build_crud(
    ns="accounts", name="link", slug="links", model_class=ParentStudentLink,
    form_cls=ParentStudentLinkForm, title="Parent-Student Links", singular="Link",
    columns=[("Parent", "parent.display_name"), ("Student", "student.full_name"),
             ("Class", "student.class_ref"), ("Relationship", "relationship")],
    search_fields=("parent__username", "parent__first_name", "student__full_name"),
    select_related=("parent", "student", "student__class_ref"), allow_update=False,
)


@role_required(ADMIN)
def login_history(request):
    qs = LoginHistory.objects.select_related("user").all()
    q = request.GET.get("q", "").strip()
    user_id = request.GET.get("user", "").strip()
    date_from = request.GET.get("from", "").strip()
    date_to = request.GET.get("to", "").strip()

    if q: qs = qs.filter(user__username__icontains=q)
    if user_id.isdigit(): qs = qs.filter(user_id=user_id)
    if date_from: qs = qs.filter(timestamp__date__gte=date_from)
    if date_to: qs = qs.filter(timestamp__date__lte=date_to)

    page_obj, querystring = paginate(request, qs, 50)

    return render(request, "accounts/login_history.html", {
        "page_obj": page_obj, "qs": querystring, "q": q,
        "user_id": user_id, "date_from": date_from, "date_to": date_to,
    })