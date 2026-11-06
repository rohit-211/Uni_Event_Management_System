from django.contrib import admin
from .models import Announcement


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    """
    Django Admin panel configuration for managing campus announcements.
    """
    list_display = (
        'title',
        'creator',
        'audience',
        'priority',
        'status',
        'published_at',
        'created_at'
    )
    list_filter = ('status', 'priority', 'audience', 'created_at', 'published_at')
    search_fields = (
        'title',
        'content',
        'event_title',
        'creator__username',
        'creator__email',
        'creator__first_name',
        'creator__last_name'
    )
    readonly_fields = ('created_at', 'updated_at', 'published_at')
    ordering = ('-created_at',)
    list_per_page = 25
