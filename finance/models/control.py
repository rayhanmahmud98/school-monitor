from django.conf import settings
from django.db import models
from django.utils import timezone

from .base import AppendOnlyModel


class NumberSequence(models.Model):
    """Gapless counters per (key, calendar year). Always read with select_for_update."""

    key = models.CharField(max_length=40)
    year = models.PositiveSmallIntegerField()
    next_value = models.PositiveBigIntegerField(default=1)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["key", "year"], name="uniq_numseq_key_year")]

    def __str__(self):
        return f"{self.key} {self.year}: {self.next_value}"


class FinancePeriod(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"

    label = models.CharField(max_length=7, unique=True, help_text="YYYY-MM")
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                  on_delete=models.PROTECT, related_name="+")
    closed_at = models.DateTimeField(null=True, blank=True)
    reopened_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.PROTECT, related_name="+")
    reopen_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-start_date"]
        constraints = [
            models.CheckConstraint(condition=models.Q(end_date__gte=models.F("start_date")),
                                   name="financeperiod_end_after_start"),
        ]

    def __str__(self):
        return f"{self.label} ({self.get_status_display()})"


class AuditEvent(AppendOnlyModel):
    """Hash-chained, append-only audit trail for everything financial."""

    seq = models.BigIntegerField(unique=True)
    timestamp = models.DateTimeField(default=timezone.now)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.PROTECT, related_name="finance_audit_events")
    actor_label = models.CharField(max_length=150, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    event_type = models.CharField(max_length=60, db_index=True)
    object_type = models.CharField(max_length=60, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    old_values = models.JSONField(null=True, blank=True)
    new_values = models.JSONField(null=True, blank=True)
    reason = models.TextField(blank=True)
    refs = models.JSONField(default=dict, blank=True)
    prev_hash = models.CharField(max_length=64)
    hash = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ["-seq"]

    def __str__(self):
        return f"#{self.seq} {self.event_type}"
