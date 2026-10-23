"""
Generic admin-only CRUD factory so each model needs ~10 lines instead of ~80.
Returns list/create/update/delete views plus ready-made URL patterns.
"""
from types import SimpleNamespace

from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import ProtectedError, Q
from django.shortcuts import redirect
from django.urls import path, reverse, reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .models import User
from .permissions import RoleBasedAccessMixin


def build_crud(*, ns, name, slug, model_class, form_cls, title, singular, columns,
               search_fields=(), select_related=(), ordering=None,
               allow_update=True, allow_create=True, allow_delete=True,
               can_delete=None, base_queryset=None, detail_url_name=None):
    list_name = f"{ns}:{name}_list"
    admin_only = (User.Role.ADMIN,)

    class CrudList(RoleBasedAccessMixin, ListView):
        allowed_roles = admin_only
        model = model_class
        template_name = "crud/list.html"
        paginate_by = 15

        def get_queryset(self):
            qs = base_queryset if base_queryset is not None else model_class.objects.all()
            if select_related:
                qs = qs.select_related(*select_related)
            if ordering:
                qs = qs.order_by(*ordering)
            q = self.request.GET.get("q", "").strip()
            if q and search_fields:
                cond = Q()
                for field in search_fields:
                    cond |= Q(**{f"{field}__icontains": q})
                qs = qs.filter(cond)
            return qs

        def get_context_data(self, **kwargs):
            ctx = super().get_context_data(**kwargs)
            params = self.request.GET.copy()
            params.pop("page", None)
            ctx.update(
                title=title, singular=singular, columns=columns,
                create_url=reverse(f"{ns}:{name}_create") if allow_create else "",
                update_name=f"{ns}:{name}_update" if allow_update else "",
                delete_name=f"{ns}:{name}_delete" if allow_delete else "",
                detail_name=detail_url_name, # Added to enable View Profile buttons
                q=self.request.GET.get("q", ""), searchable=bool(search_fields),
                qs=params.urlencode(),
            )
            return ctx

    class CrudCreate(RoleBasedAccessMixin, SuccessMessageMixin, CreateView):
        allowed_roles = admin_only
        model = model_class
        form_class = form_cls
        template_name = "crud/form.html"
        success_url = reverse_lazy(list_name)
        success_message = f"{singular} created successfully."

        def get_context_data(self, **kwargs):
            ctx = super().get_context_data(**kwargs)
            ctx.update(title=f"Add {singular}", cancel_url=reverse(list_name))
            return ctx

    class CrudUpdate(RoleBasedAccessMixin, SuccessMessageMixin, UpdateView):
        allowed_roles = admin_only
        model = model_class
        form_class = form_cls
        template_name = "crud/form.html"
        success_url = reverse_lazy(list_name)
        success_message = f"{singular} updated successfully."

        def get_context_data(self, **kwargs):
            ctx = super().get_context_data(**kwargs)
            ctx.update(title=f"Edit {singular}", cancel_url=reverse(list_name))
            return ctx

    class CrudDelete(RoleBasedAccessMixin, DeleteView):
        allowed_roles = admin_only
        model = model_class
        template_name = "crud/confirm_delete.html"
        success_url = reverse_lazy(list_name)

        def get_context_data(self, **kwargs):
            ctx = super().get_context_data(**kwargs)
            ctx.update(title=f"Delete {singular}", cancel_url=reverse(list_name))
            return ctx

        def form_valid(self, form):
            if can_delete and not can_delete(self.object, self.request):
                messages.error(self.request, "You cannot delete this record.")
                return redirect(list_name)
            try:
                response = super().form_valid(form)
            except ProtectedError:
                messages.error(self.request, "This record is still referenced by other data "
                                             "and cannot be deleted.")
                return redirect(list_name)
            messages.success(self.request, f"{singular} deleted.")
            return response

    urls = [path(f"{slug}/", CrudList.as_view(), name=f"{name}_list")]
    if allow_create:
        urls.append(path(f"{slug}/new/", CrudCreate.as_view(), name=f"{name}_create"))
    if allow_update:
        urls.append(path(f"{slug}/<int:pk>/edit/", CrudUpdate.as_view(), name=f"{name}_update"))
    if allow_delete:
        urls.append(path(f"{slug}/<int:pk>/delete/", CrudDelete.as_view(), name=f"{name}_delete"))

    return SimpleNamespace(list=CrudList, create=CrudCreate, update=CrudUpdate,
                           delete=CrudDelete, urls=urls)