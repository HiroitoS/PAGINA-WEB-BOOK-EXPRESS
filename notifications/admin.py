from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "recipient",
        "module",
        "event_type",
        "severity",
        "is_read",
        "created_at",
    )
    list_filter = (
        "module",
        "event_type",
        "severity",
        "is_read",
    )
    search_fields = (
        "recipient__username",
        "recipient__first_name",
        "recipient__last_name",
        "title",
        "message",
        "source_id",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "read_at",
    )
