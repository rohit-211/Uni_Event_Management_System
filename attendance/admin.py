from django.contrib import admin
from .models import Attendance


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('registration', 'get_student', 'get_event', 'status', 'checked_in_at', 'marked_by')
    list_filter = ('status', 'method', 'checked_in_at', 'registration__event')
    search_fields = (
        'registration__user__username',
        'registration__user__email',
        'registration__user__first_name',
        'registration__user__last_name',
        'registration__event__title',
    )
    autocomplete_fields = ('registration', 'marked_by')
    readonly_fields = ('created_at', 'updated_at')

    @admin.display(description='Student', ordering='registration__user__username')
    def get_student(self, obj):
        return obj.registration.user

    @admin.display(description='Event', ordering='registration__event__title')
    def get_event(self, obj):
        return obj.registration.event
