"""Permission-based CRUD factory for finance configuration screens.

Same look as accounts.crud (it reuses crud/list.html and crud/form.html) but access is
decided by finance permission codenames and every change is written to the audit trail.
"""
from types import SimpleNamespace

from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.db import transaction
from django.db.models import ProtectedError, Q
from django.shortcuts import redirect
from django.urls import path, reverse, reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .permissions import FinancePermissionMixin
from .services import audit


def build_finance_crud(*, name, slug, model_class, form_cls, title, singular, columns, permission,
                       event_prefix, search_fields=(), select_related=(), ordering=None,
                       allow_delete=True, can_delete=None, ns="finance"):
    list_name = f"{ns}:{name}_list"

    class CrudList(FinancePermissionMixin, ListView):
        required_permission = permission
        model = model_class
        template_name = "crud/list.html"
        paginate_by = 15

        def get_queryset(self):
            qs = model_class.objects.all()
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
                create_url=reverse(f"{ns}:{name}_create"),
                update_name=f"{ns}:{name}_update",
                delete_name=f"{ns}:{name}_delete" if allow_delete else "",
                detail_name=None, q=self.request.GET.get("q", ""),
                searchable=bool(search_fields), qs=params.urlencode())
            return ctx

    class CrudCreate(FinancePermissionMixin, SuccessMessageMixin, CreateView):
        required_permission = permission
        model = model_class
        form_class = form_cls
        template_name = "crud/form.html"
        success_url = reverse_lazy(list_name)
        success_message = f"{singular} created."

        def get_context_data(self, **kwargs):
            ctx = super().get_context_data(**kwargs)
            ctx.update(title=f"Add {singular}", cancel_url=reverse(list_name))
            return ctx

        def form_valid(self, form):
            with transaction.atomic():
                response = super().form_valid(form)
                audit.record(actor=self.request.user, event_type=f"{event_prefix}.created",
                             obj=self.object, new=audit.snapshot(self.object), request=self.request)
            return response

    class CrudUpdate(FinancePermissionMixin, SuccessMessageMixin, UpdateView):
        required_permission = permission
        model = model_class
        form_class = form_cls
        template_name = "crud/form.html"
        success_url = reverse_lazy(list_name)
        success_message = f"{singular} updated."

        def get_object(self, queryset=None):
            obj = super().get_object(queryset)
            self._old = audit.snapshot(obj)
            return obj

        def get_context_data(self, **kwargs):
            ctx = super().get_context_data(**kwargs)
            ctx.update(title=f"Edit {singular}", cancel_url=reverse(list_name))
            return ctx

        def form_valid(self, form):
            with transaction.atomic():
                response = super().form_valid(form)
                audit.record(actor=self.request.user, event_type=f"{event_prefix}.updated",
                             obj=self.object, old=self._old, new=audit.snapshot(self.object),
                             request=self.request)
            return response

    class CrudDelete(FinancePermissionMixin, DeleteView):
        required_permission = permission
        model = model_class
        template_name = "crud/confirm_delete.html"
        success_url = reverse_lazy(list_name)

        def get_context_data(self, **kwargs):
            ctx = super().get_context_data(**kwargs)
            ctx.update(title=f"Delete {singular}", cancel_url=reverse(list_name))
            return ctx

        def form_valid(self, form):
            if can_delete and not can_delete(self.object, self.request):
                messages.error(self.request, "This record cannot be deleted.")
                return redirect(list_name)
            snap, pk = audit.snapshot(self.object), self.object.pk
            try:
                with transaction.atomic():
                    response = super().form_valid(form)
                    audit.record(actor=self.request.user, event_type=f"{event_prefix}.deleted",
                                 object_type=model_class.__name__, object_id=str(pk), old=snap,
                                 request=self.request)
            except ProtectedError:
                messages.error(self.request, "This record is used elsewhere and cannot be deleted.")
                return redirect(list_name)
            messages.success(self.request, f"{singular} deleted.")
            return response

    urls = [
        path(f"{slug}/", CrudList.as_view(), name=f"{name}_list"),
        path(f"{slug}/new/", CrudCreate.as_view(), name=f"{name}_create"),
        path(f"{slug}/<int:pk>/edit/", CrudUpdate.as_view(), name=f"{name}_update"),
    ]
    if allow_delete:
        urls.append(path(f"{slug}/<int:pk>/delete/", CrudDelete.as_view(), name=f"{name}_delete"))
    return SimpleNamespace(list=CrudList, create=CrudCreate, update=CrudUpdate, delete=CrudDelete,
                           urls=urls)
