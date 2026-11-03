"""Data migration: give every existing student a current Enrollment row.

Before this, nothing in the application created Enrollment rows, so the table
was empty. Finance needs one enrollment per active student.
"""
from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    Student = apps.get_model("students", "Student")
    Enrollment = apps.get_model("students", "Enrollment")
    today = timezone.localdate()
    already = set(Enrollment.objects.values_list("student_id", flat=True))
    rows = [
        Enrollment(
            student_id=s.pk,
            class_ref_id=s.class_ref_id,
            enrolled_on=s.admission_date or today,
            is_current=s.is_active,
        )
        for s in Student.objects.exclude(pk__in=already).iterator()
    ]
    Enrollment.objects.bulk_create(rows, batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("students", "0006_alter_studentdocument_file"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
