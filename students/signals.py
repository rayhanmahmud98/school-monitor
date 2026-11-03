"""Keep Enrollment rows in step with Student records.

Connected in students/apps.py -> ready(). Finance listens to Enrollment
creation to generate invoices, so every admission, class change and
deactivation must be reflected here.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import Enrollment, Student


@receiver(post_save, sender=Student)
def sync_enrollment(sender, instance, created, raw=False, **kwargs):
    if raw:  # loaddata / fixtures
        return
    today = timezone.localdate()
    current = (
        Enrollment.objects.filter(student=instance, is_current=True)
        .order_by("-enrolled_on", "-pk")
        .first()
    )

    if not instance.is_active:
        if current:
            current.is_current = False
            current.left_on = current.left_on or today
            current.save(update_fields=["is_current", "left_on"])
        return

    if current and current.class_ref_id == instance.class_ref_id:
        return

    if current:  # class changed: close the old enrollment
        current.is_current = False
        current.left_on = current.left_on or today
        current.save(update_fields=["is_current", "left_on"])

    enrolled_on = instance.admission_date if (created and instance.admission_date) else today
    enrollment, made = Enrollment.objects.get_or_create(
        student=instance, class_ref=instance.class_ref, enrolled_on=enrolled_on,
        defaults={"is_current": True},
    )
    if not made and (not enrollment.is_current or enrollment.left_on):
        enrollment.is_current = True
        enrollment.left_on = None
        enrollment.save(update_fields=["is_current", "left_on"])
