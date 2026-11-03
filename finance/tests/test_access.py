"""Roles, groups and who may open which finance page."""
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from finance.permissions import user_can

from .helpers import current_period, make_class, make_student, make_user, make_year, set_fee, make_category
from finance.services import invoicing


class RoleGroupTests(TestCase):
    def test_finance_roles_land_in_their_group(self):
        for role, group in (("ACCOUNTANT", "Finance - Accountant"), ("CLERK", "Finance - Clerk"),
                            ("AUDITOR", "Finance - Auditor")):
            user = make_user(f"u_{role}", role)
            self.assertEqual(list(user.groups.values_list("name", flat=True)), [group])

    def test_changing_role_moves_the_group(self):
        user = make_user("mover", "CLERK")
        user.role = "AUDITOR"
        user.save()
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["Finance - Auditor"])
        user.role = "TEACHER"
        user.save()
        self.assertEqual(user.groups.count(), 0)

    def test_permission_matrix_defaults(self):
        acct, clerk, auditor = (make_user("a", "ACCOUNTANT"), make_user("c", "CLERK"),
                                make_user("v", "AUDITOR"))
        self.assertTrue(user_can(acct, "generate_invoice"))
        self.assertTrue(user_can(acct, "award_discount"))
        self.assertFalse(user_can(acct, "manage_feecategory"))       # admin-only by default
        self.assertFalse(user_can(acct, "view_audit"))
        self.assertFalse(user_can(clerk, "generate_invoice"))
        self.assertTrue(user_can(clerk, "enter_payment"))
        self.assertTrue(user_can(auditor, "view_audit"))
        self.assertTrue(user_can(auditor, "approve_discount"))
        self.assertFalse(user_can(auditor, "generate_invoice"))


class PageAccessTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin", "ADMIN")
        self.acct = make_user("acct", "ACCOUNTANT")
        self.clerk = make_user("clerk", "CLERK")
        self.auditor = make_user("aud", "AUDITOR")
        self.parent = make_user("par", "PARENT")
        self.teacher = make_user("tea", "TEACHER")
        year = make_year()
        cls = make_class(year)
        make_student(cls, 1)
        cat = make_category()
        set_fee(cat, year, cls, "1000", self.admin)
        invoicing.generate_bulk(current_period(year), self.admin)
        from finance.models import StudentInvoice
        self.invoice = StudentInvoice.objects.get()

    def status(self, user, name, *args):
        if user:
            self.client.force_login(user)
        return self.client.get(reverse(name, args=args)).status_code

    def test_anonymous_is_sent_to_login(self):
        resp = self.client.get(reverse("finance:home"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp["Location"])

    def test_parents_and_teachers_are_forbidden_everywhere(self):
        for user in (self.parent, self.teacher):
            for name, args in (("finance:home", ()), ("finance:invoice_list", ()),
                               ("finance:invoice_detail", (self.invoice.pk,)),
                               ("finance:matrix", ()), ("finance:audit_list", ())):
                self.assertEqual(self.status(user, name, *args), 403, (user.username, name))

    def test_finance_staff_can_read_invoices(self):
        for user in (self.admin, self.acct, self.clerk, self.auditor):
            self.assertEqual(self.status(user, "finance:invoice_list"), 200, user.username)
            self.assertEqual(self.status(user, "finance:invoice_detail", self.invoice.pk), 200)
            self.assertEqual(self.status(user, "finance:home"), 200)

    def test_configuration_is_admin_only_by_default(self):
        for name in ("finance:matrix", "finance:category_list", "finance:period_list",
                     "finance:installmentoption_list", "finance:discountrule_list"):
            self.assertEqual(self.status(self.admin, name), 200, name)
            for user in (self.acct, self.clerk, self.auditor):
                self.assertEqual(self.status(user, name), 403, (user.username, name))

    def test_generation_and_adjustment_permissions(self):
        self.assertEqual(self.status(self.acct, "finance:invoice_generate"), 200)
        self.assertEqual(self.status(self.clerk, "finance:invoice_generate"), 403)
        self.assertEqual(self.status(self.acct, "finance:invoice_adjust", self.invoice.pk), 200)
        self.assertEqual(self.status(self.auditor, "finance:invoice_adjust", self.invoice.pk), 403)

    def test_audit_trail_visible_to_admin_and_auditor_only(self):
        self.assertEqual(self.status(self.admin, "finance:audit_list"), 200)
        self.assertEqual(self.status(self.auditor, "finance:audit_list"), 200)
        self.assertEqual(self.status(self.acct, "finance:audit_list"), 403)

    def test_finance_roles_cannot_open_academic_pages(self):
        for user in (self.acct, self.clerk, self.auditor):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("accounts:user_list")).status_code, 403)

    def test_login_redirect_sends_finance_roles_home(self):
        self.client.force_login(self.acct)
        resp = self.client.get(reverse("dashboard:home"))
        self.assertRedirects(resp, reverse("finance:home"), fetch_redirect_response=False)

    def test_posting_writes_audit_not_generic_log(self):
        from academics.models import AuditLog
        from finance.models import AuditEvent
        self.client.force_login(self.admin)
        before = AuditLog.objects.count()
        self.client.post(reverse("finance:invoice_cancel", args=[self.invoice.pk]), {"reason": "test"})
        self.assertEqual(AuditLog.objects.count(), before)          # middleware skips finance
        self.assertTrue(AuditEvent.objects.filter(event_type="invoice.cancelled").exists())

    def test_matrix_save_flow(self):
        from finance.models import FeeRule
        year = make_year()
        cls = make_class(year, name="Class 7")
        cat = make_category(code="LAB", name="Lab", frequency="ANNUAL")
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("finance:matrix"), {
            "action": "save", "year": year.pk, "effective_from": f"{year.start_date.year}-01-01",
            f"amt_{cat.pk}_{cls.pk}": "750"})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(FeeRule.objects.filter(fee_category=cat, class_ref=cls, amount=750).exists())

    def test_category_delete_blocked_when_used(self):
        from finance.models import FeeCategory
        cat = FeeCategory.objects.get(code="TUITION")
        self.client.force_login(self.admin)
        self.client.post(reverse("finance:category_delete", args=[cat.pk]))
        self.assertTrue(FeeCategory.objects.filter(pk=cat.pk).exists())
