from django.db import models
from django.conf import settings
from django.utils import timezone


class Audience(models.TextChoices):
    """
    Target audience choices for university announcements:
    - ALL: University-wide broadcast visible to all students, organisers, and administrators.
    - STUDENTS: Targeted specifically to students.
    - ORGANISERS: Targeted specifically to event organisers.
    """
    ALL = 'ALL', 'All Users (University-Wide)'
    STUDENTS = 'STUDENTS', 'Students Only'
    ORGANISERS = 'ORGANISERS', 'Organisers Only'


class Priority(models.TextChoices):
    """
    Priority levels indicating urgency of the broadcast:
    - NORMAL: Standard routine update or notice.
    - IMPORTANT: Significant event update, scheduling change, or registration alert.
    - URGENT: Critical deadline, emergency cancellation, or vital campus advisory.
    """
    NORMAL = 'NORMAL', 'Normal'
    IMPORTANT = 'IMPORTANT', 'Important'
    URGENT = 'URGENT', 'Urgent'


class Status(models.TextChoices):
    """
    Publication lifecycle status:
    - DRAFT: Work in progress; visible only to the author and system administrators.
    - PUBLISHED: Officially live; visible to the designated audience.
    """
    DRAFT = 'DRAFT', 'Draft'
    PUBLISHED = 'PUBLISHED', 'Published'


class Announcement(models.Model):
    """
    Core data model for campus broadcasts and event-related notifications.
    Supports role-based audience targeting, priority indicators, and publication status.
    """
    title = models.CharField(
        max_length=200,
        help_text="Clear, concise headline for the announcement."
    )
    content = models.TextField(
        help_text="Detailed body text containing full notice or event instructions."
    )
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='announcements',
        help_text="The campus user (Admin or Organiser) who authored this announcement."
    )
    event_title = models.CharField(
        max_length=200,
        blank=True,
        help_text="Optional associated event title or reference (e.g. 'Annual Tech Fest 2026')."
    )
    audience = models.CharField(
        max_length=20,
        choices=Audience.choices,
        default=Audience.ALL,
        db_index=True,
        help_text="Specifies who can view this announcement."
    )
    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.NORMAL,
        db_index=True,
        help_text="Urgency level displayed to students and organisers."
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PUBLISHED,
        db_index=True,
        help_text="Drafts are hidden from regular users until published."
    )
    published_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Timestamp when the announcement was officially made public."
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="Timestamp when the record was initially authored."
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when the record was last modified."
    )

    class Meta:
        verbose_name = 'Announcement'
        verbose_name_plural = 'Announcements'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_priority_display()}] {self.title} ({self.get_audience_display()})"

    def save(self, *args, **kwargs):
        """
        Automatically populate or clear published_at based on publication status.
        """
        if self.status == Status.PUBLISHED and not self.published_at:
            self.published_at = timezone.now()
        elif self.status == Status.DRAFT:
            self.published_at = None
        super().save(*args, **kwargs)

    @property
    def is_published(self):
        return self.status == Status.PUBLISHED

    @property
    def is_urgent(self):
        return self.priority == Priority.URGENT

    @property
    def is_important(self):
        return self.priority == Priority.IMPORTANT
