"""
The ONLY finance module that imports school apps (students, accounts, academics).
Everything else in finance goes through these functions, which keeps the finance
logic reusable for other organisations later.
"""
from academics.models import AcademicYear
from students.models import Class, Enrollment, ParentStudentLink, Student  # noqa: F401


class AcademicYearMismatch(Exception):
    """A class's academic_year text matches no AcademicYear row."""


def academic_year_for_class(class_ref):
    """Resolve a class's year by exact name; never guess."""
    try:
        return AcademicYear.objects.get(name=class_ref.academic_year)
    except AcademicYear.DoesNotExist:
        raise AcademicYearMismatch(
            f"Class {class_ref} has academic year {class_ref.academic_year!r}, "
            "which does not match any Academic Year. Run: python manage.py check_academic_years"
        ) from None


def search_students(query, limit=20):
    """Active students by name or student_id (for payment-entry autocomplete)."""
    from django.db.models import Q
    query = (query or "").strip()
    qs = Student.objects.filter(is_active=True).select_related("class_ref")
    if query:
        qs = qs.filter(Q(full_name__icontains=query) | Q(student_id__icontains=query))
    return qs.order_by("full_name")[:limit]


def sibling_rank(student):
    """1 for the eldest enrolled child, 2 for the next, and so on.

    Siblings are active students who share a linked parent account.
    """
    from django.db.models import F

    parent_ids = list(ParentStudentLink.objects.filter(student=student)
                      .values_list("parent_id", flat=True))
    if not parent_ids:
        return 1
    ids = list(
        Student.objects.filter(parent_links__parent_id__in=parent_ids, is_active=True)
        .distinct()
        .order_by(F("admission_date").asc(nulls_last=True), "pk")
        .values_list("pk", flat=True)
    )
    return ids.index(student.pk) + 1 if student.pk in ids else 1


def active_students_for_year(year_name, class_ref=None):
    """Active students whose class belongs to the academic year named `year_name`."""
    qs = Student.objects.filter(is_active=True, class_ref__academic_year=year_name)
    if class_ref is not None:
        qs = qs.filter(class_ref=class_ref)
    return qs.select_related("class_ref").order_by("class_ref", "roll_no")
