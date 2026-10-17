from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


# This username can never be deleted or deactivated by anyone.
PRIMARY_ADMIN_USERNAME = "admin"


class User(AbstractUser):
    """Custom user with a single role that drives all permissions."""

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        TEACHER = "TEACHER", "Teacher"
        PARENT = "PARENT", "Parent"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.PARENT)

    def save(self, *args, **kwargs):
        # Superusers are always admins; admins may enter Django's /django-admin/ site.
        if self.is_superuser:
            self.role = self.Role.ADMIN
        if self.role == self.Role.ADMIN:
            self.is_staff = True
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    @property
    def is_primary_admin(self):
        """True for the one protected account that nobody can delete or deactivate."""
        return self.username == PRIMARY_ADMIN_USERNAME

    def __str__(self):
        return f"{self.display_name} ({self.get_role_display()})"


class ParentProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="parent_profile")
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)

    def __str__(self):
        return f"Parent profile: {self.user.username}"


class TeacherProfile(models.Model):
    class Designation(models.TextChoices):
        PRINCIPAL = "PRINCIPAL", "Principal"
        VICE_PRINCIPAL = "VICE_PRINCIPAL", "Vice Principal"
        HEAD_OF_DEPT = "HEAD_OF_DEPT", "Head of Department"
        SENIOR_TEACHER = "SENIOR_TEACHER", "Senior Teacher"
        ASSISTANT_TEACHER = "ASSISTANT_TEACHER", "Assistant Teacher"
        LECTURER = "LECTURER", "Lecturer"
        INSTRUCTOR = "INSTRUCTOR", "Instructor"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="teacher_profile")
    subject_specialization = models.CharField(max_length=100, blank=True)
    designation = models.CharField(
        max_length=30,
        choices=Designation.choices,
        default=Designation.ASSISTANT_TEACHER,
        blank=True,
        help_text="Select the teacher's role.",
    )
    phone = models.CharField(max_length=30, blank=True)

    def __str__(self):
        return f"Teacher profile: {self.user.username}"


class LoginHistory(models.Model):
    """Records every successful login for the audit trail."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="login_history",
    )
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    session_key = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Login history"
        verbose_name_plural = "Login histories"

    def __str__(self):
        when = self.timestamp.strftime("%Y-%m-%d %H:%M") if self.timestamp else "?"
        return f"{self.user} logged in at {when}"