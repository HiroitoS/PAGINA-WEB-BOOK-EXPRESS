from django.contrib import admin

from .models import (
    ContactRequest,
    ContactRequestComment,
    ContactRequestStatusHistory,
)


class ContactRequestCommentInline(admin.TabularInline):
    model = ContactRequestComment
    extra = 1
    fields = (
        "user",
        "action_type",
        "comment",
        "created_at",
        "updated_at",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )


class ContactRequestStatusHistoryInline(admin.TabularInline):
    model = ContactRequestStatusHistory
    extra = 0
    fields = (
        "changed_by",
        "old_status",
        "new_status",
        "note",
        "created_at",
    )
    readonly_fields = (
        "changed_by",
        "old_status",
        "new_status",
        "note",
        "created_at",
    )
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


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
        "priority",
        "assigned_to",
        "last_attention_at",
        "next_action_at",
        "created_at",
    )
    list_filter = (
        "source",
        "status",
        "priority",
        "assigned_to",
        "created_at",
        "last_attention_at",
    )
    search_fields = (
        "full_name",
        "phone",
        "email",
        "message",
        "product__name",
        "provider__name",
        "assigned_to__username",
        "assigned_to__first_name",
        "assigned_to__last_name",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "last_attention_at",
        "closed_at",
    )
    ordering = ("-created_at",)
    inlines = [
        ContactRequestCommentInline,
        ContactRequestStatusHistoryInline,
    ]


@admin.register(ContactRequestComment)
class ContactRequestCommentAdmin(admin.ModelAdmin):
    list_display = (
        "contact_request",
        "user",
        "action_type",
        "created_at",
    )
    list_filter = (
        "action_type",
        "created_at",
    )
    search_fields = (
        "contact_request__full_name",
        "contact_request__phone",
        "comment",
        "user__username",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )
    ordering = ("-created_at",)


@admin.register(ContactRequestStatusHistory)
class ContactRequestStatusHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "contact_request",
        "changed_by",
        "old_status",
        "new_status",
        "created_at",
    )
    list_filter = (
        "old_status",
        "new_status",
        "created_at",
    )
    search_fields = (
        "contact_request__full_name",
        "contact_request__phone",
        "changed_by__username",
        "note",
    )
    readonly_fields = (
        "contact_request",
        "changed_by",
        "old_status",
        "new_status",
        "note",
        "created_at",
    )
    ordering = ("-created_at",)