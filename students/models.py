from django.conf import settings
from django.db import models
from django.utils import timezone


def _next_student_id():
    """STU-YYYY-NNNN, scoped per year."""
    year = timezone.localdate().year
    prefix = f"STU-{year}-"
    last = (
        Student.objects.filter(student_id__startswith=prefix)
        .order_by("-student_id")
        .values_list("student_id", flat=True)
        .first()
    )
    if last:
        try:
            n = int(last.rsplit("-", 1)[1]) + 1
        except (ValueError, IndexError):
            n = 1
    else:
        n = 1
    return f"{prefix}{n:04d}"


def document_upload_path(instance, filename):
    sid = instance.student.student_id or f"pk{instance.student.pk}"
    return f"student_documents/{sid}/{filename}"


class Class(models.Model):
    name = models.CharField(max_length=50)
    section = models.CharField(max_length=10, blank=True)
    academic_year = models.CharField(max_length=20)
    max_students = models.PositiveIntegerField(
        default=30,
        help_text="Maximum number of active students allowed in this class.",
    )

    class Meta:
        unique_together = ("name", "section", "academic_year")
        ordering = ["name", "section"]

    @property
    def active_student_count(self):
        return self.students.filter(is_active=True).count()

    @property
    def is_full(self):
        return self.active_student_count >= self.max_students

    @property
    def remaining_seats(self):
        return max(self.max_students - self.active_student_count, 0)
    def __str__(self):
        return f"{self.name} - {self.section} ({self.academic_year})"


class Subject(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20)
    class_ref = models.ForeignKey(Class, on_delete=models.CASCADE, related_name="subjects")
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="subjects",
        limit_choices_to={"role": "TEACHER"},
    )

    class Meta:
        unique_together = ("code", "class_ref")
        ordering = ["class_ref", "name"]

    def __str__(self):
        return f"{self.name} ({self.code}) - {self.class_ref}"


class Student(models.Model):
    class Gender(models.TextChoices):
        MALE = "M", "Male"
        FEMALE = "F", "Female"
        OTHER = "O", "Other"

    class BloodGroup(models.TextChoices):
        A_POS = "A+", "A+"
        A_NEG = "A-", "A-"
        B_POS = "B+", "B+"
        B_NEG = "B-", "B-"
        AB_POS = "AB+", "AB+"
        AB_NEG = "AB-", "AB-"
        O_POS = "O+", "O+"
        O_NEG = "O-", "O-"

    student_id = models.CharField(max_length=20, unique=True, blank=True,
                                  help_text="Auto-generated, e.g. STU-2026-0001")
    first_name = models.CharField(max_length=60)
    middle_name = models.CharField(max_length=60, blank=True)
    last_name = models.CharField(max_length=60)
    preferred_name = models.CharField(max_length=60, blank=True)
    full_name = models.CharField(max_length=180, blank=True)
    photo = models.ImageField(upload_to="student_photos/", null=True, blank=True)
    blood_group = models.CharField(max_length=3, choices=BloodGroup.choices, blank=True)

    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=1, choices=Gender.choices, blank=True)
    nationality = models.CharField(max_length=60, blank=True)
    ethnicity = models.CharField(max_length=60, blank=True)
    religion = models.CharField(max_length=60, blank=True)

    roll_no = models.PositiveIntegerField()
    class_ref = models.ForeignKey(Class, on_delete=models.CASCADE, related_name="students")
    admission_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    address_line1 = models.CharField(max_length=120, blank=True)
    address_line2 = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=60, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    mailing_address = models.TextField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)

    guardian_name = models.CharField(max_length=120, blank=True)
    contact = models.CharField(max_length=30, blank=True)
    user_link = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="student_records",
    )

    class Meta:
        unique_together = ("class_ref", "roll_no")
        ordering = ["class_ref", "roll_no"]

    def _compose_full_name(self):
        parts = [self.first_name, self.middle_name, self.last_name]
        return " ".join(p for p in parts if p).strip()

    def save(self, *args, **kwargs):
        if not self.student_id:
            self.student_id = _next_student_id()
        if self.first_name or self.last_name:
            self.full_name = self._compose_full_name()
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.preferred_name or self.first_name or self.full_name

    def __str__(self):
        return f"{self.full_name} ({self.class_ref})"


class ParentStudentLink(models.Model):
    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="student_links", limit_choices_to={"role": "PARENT"},
    )
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="parent_links")
    relationship = models.CharField(max_length=50, blank=True)
    is_primary = models.BooleanField(default=False)

    class Meta:
        unique_together = ("parent", "student")
        ordering = ["parent__username", "student__full_name"]

    def __str__(self):
        return f"{self.parent.display_name} -> {self.student.full_name}"


class EmergencyContact(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="emergency_contacts")
    name = models.CharField(max_length=120)
    relationship = models.CharField(max_length=60, blank=True)
    phone = models.CharField(max_length=30)
    email = models.EmailField(blank=True)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_primary", "name"]

    def __str__(self):
        return f"{self.name} ({self.relationship}) for {self.student.full_name}"


class AcademicHistory(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="academic_history")
    school_name = models.CharField(max_length=150)
    year = models.CharField(max_length=20)
    grade_level = models.CharField(max_length=30, blank=True)
    result = models.CharField(max_length=60, blank=True)
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-year"]
        verbose_name_plural = "Academic histories"

    def __str__(self):
        return f"{self.school_name} ({self.year}) - {self.student.full_name}"


class Enrollment(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="enrollments")
    class_ref = models.ForeignKey(Class, on_delete=models.CASCADE, related_name="enrollments")
    enrolled_on = models.DateField(default=timezone.localdate)
    left_on = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=True)

    class Meta:
        ordering = ["-enrolled_on"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "class_ref", "enrolled_on"],
                name="uniq_student_class_enrolled_on",
            )
        ]

    def __str__(self):
        end = self.left_on.strftime("%Y-%m-%d") if self.left_on else "present"
        return f"{self.student.full_name} in {self.class_ref} ({self.enrolled_on} -> {end})"


class StudentDocument(models.Model):
    class Kind(models.TextChoices):
        BIRTH_CERTIFICATE = "BIRTH_CERT", "Birth certificate"
        NATIONAL_ID = "NID", "National ID"
        PREVIOUS_TC = "PREV_TC", "Previous transfer certificate"
        PASSPORT_PHOTO = "PHOTO", "Passport photo"
        REPORT_CARD = "REPORT", "Previous report card"
        MEDICAL = "MEDICAL", "Medical certificate"
        OTHER = "OTHER", "Other"

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="documents")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.OTHER)
    title = models.CharField(max_length=120, blank=True)
    file = models.FileField(upload_to=document_upload_path)
    notes = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="uploaded_documents",
    )
    uploaded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-uploaded_at"]
        indexes = [models.Index(fields=["student", "-uploaded_at"])]

    @property
    def display_title(self):
        return self.title or self.get_kind_display()

    @property
    def filename(self):
        return self.file.name.rsplit("/", 1)[-1] if self.file else ""

    def __str__(self):
        return f"{self.display_title} — {self.student.full_name}"
    

def document_upload_path(instance, filename):
    sid = instance.student.student_id or f"pk{instance.student.pk}"
    return f"student_documents/{sid}/{filename}"


# class StudentDocument(models.Model):
#     class Kind(models.TextChoices):
#         BIRTH_CERTIFICATE = "BIRTH_CERT", "Birth certificate"
#         NATIONAL_ID = "NID", "National ID"
#         PREVIOUS_TC = "PREV_TC", "Previous transfer certificate"
#         PASSPORT_PHOTO = "PHOTO", "Passport photo"
#         REPORT_CARD = "REPORT", "Previous report card"
#         MEDICAL = "MEDICAL", "Medical certificate"
#         OTHER = "OTHER", "Other"

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="documents")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.OTHER)
    title = models.CharField(max_length=120, blank=True)
    file = models.FileField(upload_to=document_upload_path)
    notes = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="uploaded_documents",
    )
    uploaded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-uploaded_at"]
        indexes = [models.Index(fields=["student", "-uploaded_at"])]

    @property
    def display_title(self):
        return self.title or self.get_kind_display()

    @property
    def filename(self):
        return self.file.name.rsplit("/", 1)[-1] if self.file else ""

    def __str__(self):
        return f"{self.display_title} — {self.student.full_name}"


class TransferCertificate(models.Model):
    """A formal TC issued to a student when they leave the school.

    One per student. Issuing a TC also marks the student inactive.
    """

    class Reason(models.TextChoices):
        GRADUATION = "GRAD", "Completed studies / graduation"
        RELOCATION = "RELOC", "Family relocation"
        TRANSFER = "TRAN", "Transfer to another school"
        MEDICAL = "MED", "Medical reasons"
        OTHER = "OTHER", "Other"

    student = models.OneToOneField(
        Student, on_delete=models.CASCADE, related_name="transfer_certificate"
    )
    tc_number = models.CharField(
        max_length=30, unique=True, blank=True,
        help_text="Auto-generated as TC-YYYY-NNNN if left blank.",
    )
    reason = models.CharField(
        max_length=10, choices=Reason.choices, default=Reason.RELOCATION
    )
    reason_note = models.CharField(
        max_length=200, blank=True,
        help_text="Optional detail, e.g. 'Father posted to Dubai'.",
    )
    conduct = models.CharField(
        max_length=60, default="Good", blank=True,
        help_text="e.g. Excellent, Good, Satisfactory.",
    )
    dues_cleared = models.BooleanField(
        default=True,
        help_text="School fees and library materials returned.",
    )
    date_of_leaving = models.DateField(
        default=timezone.localdate,
        help_text="The student's last day at the school.",
    )
    remarks = models.TextField(blank=True)
    issued_at = models.DateTimeField(default=timezone.now)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="issued_tcs",
    )

    class Meta:
        ordering = ["-issued_at"]
        verbose_name = "Transfer Certificate"
        verbose_name_plural = "Transfer Certificates"

    def save(self, *args, **kwargs):
        if not self.tc_number:
            year = timezone.localdate().year
            prefix = f"TC-{year}-"
            last = (
                TransferCertificate.objects
                .filter(tc_number__startswith=prefix)
                .order_by("-tc_number")
                .values_list("tc_number", flat=True)
                .first()
            )
            if last:
                try:
                    n = int(last.rsplit("-", 1)[1]) + 1
                except (ValueError, IndexError):
                    n = 1
            else:
                n = 1
            self.tc_number = f"{prefix}{n:04d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"TC {self.tc_number} - {self.student.full_name}"
