from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
import uuid
from django.core.exceptions import ValidationError



class AcademicYear(models.Model):
    name = models.CharField(max_length=20, unique=True, help_text="e.g. 2026-2027")
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ["-name"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_current:  # only one current year
            AcademicYear.objects.exclude(pk=self.pk).update(is_current=False)

    def __str__(self):
        return self.name


class GradeScale(models.Model):
    """Configurable grading scale. Falls back to defaults in services.py if empty."""

    min_percent = models.DecimalField(max_digits=5, decimal_places=2, unique=True)
    grade = models.CharField(max_length=5)
    gpa_points = models.DecimalField(max_digits=3, decimal_places=2)

    class Meta:
        ordering = ["-min_percent"]

    def __str__(self):
        return f"{self.grade} (>= {self.min_percent}%) = {self.gpa_points}"


class ExamType(models.Model):
    """Lookup table for exam categories: Midterm, Final, Unit Test, etc.

    Used to group exams of the same kind across academic years for reports.
    """

    name = models.CharField(max_length=60, unique=True)
    description = models.CharField(max_length=200, blank=True)
    weight = models.PositiveSmallIntegerField(
        default=100,
        help_text="Relative weight when averaging across exams of the same type.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Exam(models.Model):
    name = models.CharField(max_length=100, help_text="e.g. Midterm")
    academic_year = models.CharField(max_length=20)
    exam_type = models.ForeignKey(
        ExamType,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="exams",
        help_text="Category: Midterm, Final, Unit Test, etc.",
    )
    start_date = models.DateField()
    end_date = models.DateField()
    is_published = models.BooleanField(
        default=False, help_text="Parents can see marks for published exams only.")

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.name} ({self.academic_year})"


class Attendance(models.Model):
    class Status(models.TextChoices):
        PRESENT = "PRESENT", "Present"
        ABSENT = "ABSENT", "Absent"
        LATE = "LATE", "Late"
        EXCUSED = "EXCUSED", "Excused"

    student = models.ForeignKey("students.Student", on_delete=models.CASCADE,
                                related_name="attendance_records")
    date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PRESENT)
    marked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                  related_name="attendance_marked")
    marked_at = models.DateTimeField(default=timezone.now)
    remarks = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-date", "student__class_ref", "student__roll_no"]
        constraints = [models.UniqueConstraint(fields=["student", "date"], name="uniq_student_date")]

    def __str__(self):
        return f"{self.student.full_name} {self.date} {self.status}"


class Marksheet(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        APPROVED = "APPROVED", "Approved"

    student = models.ForeignKey("students.Student", on_delete=models.CASCADE,
                                related_name="marksheets")
    subject = models.ForeignKey("students.Subject", on_delete=models.CASCADE,
                                related_name="marksheets")
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="marksheets")
    marks_obtained = models.DecimalField(max_digits=6, decimal_places=2)
    max_marks = models.DecimalField(max_digits=6, decimal_places=2, default=100)
    grade = models.CharField(max_length=5, blank=True, editable=False)  # auto-calculated
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                   related_name="marksheets_entered")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="marksheets_approved")
    rejection_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["exam", "subject", "student__roll_no"]
        constraints = [models.UniqueConstraint(fields=["student", "subject", "exam"],
                                               name="uniq_student_subject_exam")]

    @property
    def percentage(self):
        return float(self.marks_obtained) / float(self.max_marks) * 100 if self.max_marks else 0.0

    def clean(self):
        if self.marks_obtained is not None and self.max_marks is not None:
            if self.marks_obtained < 0 or self.marks_obtained > self.max_marks:
                raise ValidationError("Marks must be between 0 and the maximum marks.")

    def save(self, *args, **kwargs):
        from .services import grade_for  # local import avoids circular import
        self.grade = grade_for(self.percentage)[0]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student.full_name} - {self.subject.name} - {self.exam.name}"


class ReportCard(models.Model):
    student = models.ForeignKey("students.Student", on_delete=models.CASCADE,
                                related_name="report_cards")
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="report_cards")
    pdf_file = models.FileField(upload_to="report_cards/", blank=True)
    generated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="report_cards_published")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["student", "exam"], name="uniq_student_exam_rc")]

    @property
    def is_published(self):
        return self.published_at is not None

    def __str__(self):
        return f"Report card: {self.student.full_name} / {self.exam.name}"


class AuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                             related_name="audit_entries")
    action = models.CharField(max_length=100)
    target_model = models.CharField(max_length=100, blank=True)
    target_id = models.PositiveIntegerField(null=True, blank=True)
    details = models.TextField(blank=True)
    timestamp = models.DateTimeField(default=timezone.now)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M} {self.user} {self.action}"



class LeaveApplication(models.Model):
    """A request for leave by a student or a teacher.

    On approval of a student leave, EXCUSED attendance rows are written for
    every weekday in the range that isn't already marked.
    """

    class Applicant(models.TextChoices):
        STUDENT = "STUDENT", "Student"
        TEACHER = "TEACHER", "Teacher"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    applicant_type = models.CharField(
        max_length=10, choices=Applicant.choices, default=Applicant.STUDENT
    )
    student = models.ForeignKey(
        "students.Student", null=True, blank=True,
        on_delete=models.CASCADE, related_name="leave_applications",
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.CASCADE, related_name="leave_applications",
        limit_choices_to={"role": "TEACHER"},
    )
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField()
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="leaves_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="leaves_submitted",
    )
    submitted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-submitted_at"]
        indexes = [models.Index(fields=["status", "-submitted_at"])]

    @property
    def days_count(self):
        return (self.end_date - self.start_date).days + 1

    @property
    def applicant_display(self):
        if self.applicant_type == self.Applicant.STUDENT and self.student:
            return self.student.full_name
        if self.teacher:
            return self.teacher.display_name
        return "-"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError("End date cannot be before start date.")
        if self.applicant_type == self.Applicant.STUDENT and not self.student:
            raise ValidationError("A student leave must reference a student.")
        if self.applicant_type == self.Applicant.TEACHER and not self.teacher:
            raise ValidationError("A teacher leave must reference a teacher.")

    def __str__(self):
        return f"{self.applicant_display} - {self.start_date} to {self.end_date} ({self.status})"

class SchoolProfile(models.Model):
    """Singleton model for school-level settings used on official documents."""
    name = models.CharField(max_length=150, default="School Monitor")
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    logo = models.ImageField(upload_to="school/", blank=True, null=True)
    return_note = models.CharField(
        max_length=200, 
        default="If this card is found, please return it to the school office."
    )

    class Meta:
        verbose_name = "School Profile"
        verbose_name_plural = "School Profile"

    def save(self, *args, **kwargs):
        # Enforce singleton
        if not self.pk and SchoolProfile.objects.exists():
            raise ValidationError("Only one School Profile can exist.")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class IDCard(models.Model):
    """Generic verification token for student and teacher ID cards."""
    class Kind(models.TextChoices):
        STUDENT = "STUDENT", "Student"
        TEACHER = "TEACHER", "Teacher"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    student = models.OneToOneField(
        "students.Student", null=True, blank=True,
        on_delete=models.CASCADE, related_name="id_card"
    )
    teacher = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.CASCADE, related_name="id_card",
        limit_choices_to={"role": "TEACHER"}
    )
    issued_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)

    def is_valid(self):
        if self.revoked_at:
            return False
        if self.kind == self.Kind.STUDENT:
            return self.student is not None and self.student.is_active
        if self.kind == self.Kind.TEACHER:
            return self.teacher is not None and self.teacher.is_active
        return False

    def __str__(self):
        who = self.student.full_name if self.student else self.teacher.display_name if self.teacher else "Unknown"
        return f"{self.get_kind_display()} ID · {who}"