"""Report classes and exams whose academic-year text matches no AcademicYear.

Finance resolves a class's year by exact name, so mismatches must be fixed
before invoices are generated.

    python manage.py check_academic_years
"""
from django.core.management.base import BaseCommand, CommandError

from academics.models import AcademicYear, Exam
from students.models import Class


class Command(BaseCommand):
    help = "List Class/Exam academic_year values that do not match an AcademicYear name."

    def handle(self, *args, **options):
        years = list(AcademicYear.objects.all())
        names = {y.name for y in years}
        problems = []
        for pk, label in Class.objects.values_list("pk", "academic_year"):
            if label not in names:
                problems.append(f"Class #{pk}: academic_year {label!r} matches no AcademicYear")
        for pk, label in Exam.objects.values_list("pk", "academic_year"):
            if label not in names:
                problems.append(f"Exam #{pk}: academic_year {label!r} matches no AcademicYear")

        if not any(y.is_current for y in years):
            self.stdout.write(self.style.WARNING("No AcademicYear is marked as current."))
        undated = [y.name for y in years if not (y.start_date and y.end_date)]
        if undated:
            self.stdout.write(self.style.WARNING(
                "Academic years without start/end dates: " + ", ".join(undated)))

        if problems:
            for line in problems:
                self.stdout.write(self.style.ERROR(line))
            raise CommandError(f"{len(problems)} academic-year mismatch(es) found.")
        self.stdout.write(self.style.SUCCESS("All class and exam academic years match."))
