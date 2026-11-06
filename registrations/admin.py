from django.contrib import admin
from .models import Registration


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = ('event', 'user', 'status', 'created_at', 'updated_at')
    list_filter = ('status', 'event')
    search_fields = (
        'event__title',
        'user__username',
        'user__email',
        'user__first_name',
        'user__last_name',
    )
    autocomplete_fields = ('event', 'user')
    readonly_fields = ('created_at', 'updated_at')
