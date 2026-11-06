from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from accounts.models import Role, get_or_create_profile


class RegistrationStatus(models.TextChoices):
    REGISTERED = 'REGISTERED', 'Registered'
    CANCELLED = 'CANCELLED', 'Cancelled'


class Registration(models.Model):
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.PROTECT,
        related_name='registrations',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='event_registrations',
    )
    status = models.CharField(
        max_length=12,
        choices=RegistrationStatus.choices,
        default=RegistrationStatus.REGISTERED,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['event', 'user'],
                name='unique_event_registration_per_user',
            ),
        ]

    def clean(self):
        super().clean()
        if self.user_id:
            profile = get_or_create_profile(self.user)
            if profile.role != Role.STUDENT:
                raise ValidationError({'user': 'Only students can register for events.'})

    def __str__(self):
        return f'{self.user} — {self.event}'
