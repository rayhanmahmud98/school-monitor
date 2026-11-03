"""Shared fixtures for finance tests."""
from datetime import date
from decimal import Decimal

from django.utils import timezone

from academics.models import AcademicYear
from accounts.models import User
from students.models import Class, ParentStudentLink, Student

from finance.models import BillingPeriod, FeeCategory
from finance.services import fees
from finance.services.periods import create_monthly_periods


def make_user(username, role, **extra):
    return User.objects.create_user(username=username, password="pw-12345-x", role=role, **extra)


def make_year():
    today = timezone.localdate()
    year, _ = AcademicYear.objects.get_or_create(
        name=f"{today.year}-{today.year + 1}",
        defaults={"is_current": True, "start_date": date(today.year, 1, 1),
                  "end_date": date(today.year, 12, 31)})
    return year


def make_class(year, name="Class 5", section="A"):
    return Class.objects.create(name=name, section=section, academic_year=year.name)


def make_student(cls, roll, first="Test", last="Student", **extra):
    return Student.objects.create(first_name=first, last_name=last, roll_no=roll, class_ref=cls, **extra)


def make_category(code="TUITION", name="Tuition fee", frequency="MONTHLY", **extra):
    return FeeCategory.objects.create(code=code, name=name, default_frequency=frequency, **extra)


def current_period(year):
    """Monthly periods for the whole year; return the one containing today."""
    create_monthly_periods(year, issue_day=1, due_day=10)
    return BillingPeriod.objects.get(academic_year=year, kind="MONTH",
                                     label=timezone.localdate().strftime("%Y-%m"))


def set_fee(category, year, cls, amount, actor=None):
    return fees.set_amount(category, year, cls, Decimal(amount), date(timezone.localdate().year, 1, 1), actor)


def link_parent(parent, student):
    return ParentStudentLink.objects.create(parent=parent, student=student)
