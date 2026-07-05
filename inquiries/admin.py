from django.contrib import admin

from .models import ContactRequest


@admin.register(ContactRequest)
class ContactRequestAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "phone",
        "email",
        "product",
        "provider",
        "source",
        "status",
        "created_at",
    )
    list_filter = ("source", "status", "created_at")
    search_fields = (
        "full_name",
        "phone",
        "email",
        "message",
        "product__name",
        "provider__name",
    )
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)