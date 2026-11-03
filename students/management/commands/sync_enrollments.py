"""Create a current Enrollment for every active student that lacks one.

Safe to run repeatedly. Use it after loading old data into a fresh database
(loaddata skips the signals that normally create enrollments).

    python manage.py sync_enrollments
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from students.models import Enrollment, Student


class Command(BaseCommand):
    help = "Create missing current Enrollment rows for active students."

    def handle(self, *args, **options):
        today = timezone.localdate()
        have_current = set(
            Enrollment.objects.filter(is_current=True).values_list("student_id", flat=True)
        )
        created = 0
        for student in Student.objects.filter(is_active=True).exclude(pk__in=have_current):
            _, made = Enrollment.objects.get_or_create(
                student=student, class_ref=student.class_ref,
                enrolled_on=student.admission_date or today,
                defaults={"is_current": True},
            )
            if not made:  # same-day row exists but was closed: reopen it
                Enrollment.objects.filter(
                    student=student, class_ref=student.class_ref,
                    enrolled_on=student.admission_date or today,
                ).update(is_current=True, left_on=None)
            created += 1
        self.stdout.write(self.style.SUCCESS(f"{created} enrollment(s) created or reopened."))
