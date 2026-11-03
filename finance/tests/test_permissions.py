from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from accounts.models import User
from finance.permissions import FinancePermissionMixin, finance_permission_required, user_can
from finance.selectors import finance_students, portal_students


def _user(username, role, **extra):
    return User.objects.create_user(username=username, password="pw-12345-x", role=role, **extra)


class UserCanTests(TestCase):
    def test_primary_admin_has_everything(self):
        admin = _user("admin", "ADMIN")
        self.assertTrue(user_can(admin, "enter_payment"))
        self.assertTrue(user_can(admin, "reopen_period"))
        self.assertTrue(user_can(admin, "override_slip"))

    def test_secondary_admin_lacks_primary_only_actions(self):
        other = _user("admin2", "ADMIN")
        self.assertTrue(user_can(other, "enter_payment"))
        self.assertFalse(user_can(other, "reopen_period"))
        self.assertFalse(user_can(other, "override_slip"))

    def test_teacher_and_parent_denied_by_default(self):
        for role in ("TEACHER", "PARENT"):
            u = _user(f"u_{role}", role)
            self.assertFalse(user_can(u, "enter_payment"))
            self.assertFalse(user_can(u, "view_receipt"))

    def test_inactive_admin_denied(self):
        admin = _user("admin", "ADMIN", is_active=False)
        self.assertFalse(user_can(admin, "enter_payment"))

    def test_anonymous_denied(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertFalse(user_can(AnonymousUser(), "enter_payment"))


class DecoratorTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()

        @finance_permission_required("enter_payment")
        def view(request):
            return HttpResponse("ok")

        self.view = view

    def test_anonymous_redirected_to_login(self):
        request = self.rf.get("/finance/x/")
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertEqual(response.status_code, 302)

    def test_parent_gets_403(self):
        request = self.rf.get("/finance/x/")
        request.user = _user("p1", "PARENT")
        with self.assertRaises(PermissionDenied):
            self.view(request)

    def test_admin_allowed(self):
        request = self.rf.get("/finance/x/")
        request.user = _user("admin", "ADMIN")
        self.assertEqual(self.view(request).status_code, 200)

    def test_mixin_without_permission_configured_denies(self):
        class V(FinancePermissionMixin):
            def dispatch_inner(self):
                return HttpResponse("ok")

        request = self.rf.get("/finance/x/")
        request.user = _user("admin", "ADMIN")
        with self.assertRaises(PermissionDenied):
            V().dispatch(request)


class SelectorTests(TestCase):
    def test_parent_and_teacher_get_no_staff_students(self):
        for role in ("PARENT", "TEACHER"):
            self.assertEqual(finance_students(_user(f"s_{role}", role)).count(), 0)

    def test_portal_students_only_for_parents(self):
        self.assertEqual(portal_students(_user("t1", "TEACHER")).count(), 0)
        self.assertEqual(portal_students(_user("p1", "PARENT")).count(), 0)  # no links yet



