from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from registrations.models import Registration, RegistrationStatus


class AttendanceStatus(models.TextChoices):
    PRESENT = 'PRESENT', 'Present'
    ABSENT = 'ABSENT', 'Absent'


class AttendanceMethod(models.TextChoices):
    MANUAL = 'MANUAL', 'Manual'


class Attendance(models.Model):
    registration = models.OneToOneField(
        Registration,
        on_delete=models.PROTECT,
        related_name='attendance',
    )
    status = models.CharField(
        max_length=8,
        choices=AttendanceStatus.choices,
        default=AttendanceStatus.PRESENT,
        db_index=True,
    )
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='attendance_marked',
    )
    checked_in_at = models.DateTimeField(null=True, blank=True)
    method = models.CharField(
        max_length=10,
        choices=AttendanceMethod.choices,
        default=AttendanceMethod.MANUAL,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def clean(self):
        super().clean()
        if self.registration_id and self.registration.status != RegistrationStatus.REGISTERED:
            raise ValidationError({
                'registration': 'Attendance can only be recorded for an active registration.'
            })
        if self.status == AttendanceStatus.PRESENT and not self.checked_in_at:
            self.checked_in_at = timezone.now()
        elif self.status == AttendanceStatus.ABSENT:
            self.checked_in_at = None

    def __str__(self):
        return f'{self.registration} — {self.get_status_display()}'
