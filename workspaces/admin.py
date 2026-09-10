from django.contrib import admin

from .models import (
    CalendarEvent,
    Reminder,
    Task,
    TaskComment,
    TaskStatusHistory,
    WorkspaceGroup,
    WorkspaceMembership,
)


class WorkspaceMembershipInline(admin.TabularInline):
    model = WorkspaceMembership
    extra = 1


class TaskCommentInline(admin.TabularInline):
    model = TaskComment
    extra = 0
    readonly_fields = (
        "created_at",
        "updated_at",
    )


class TaskStatusHistoryInline(admin.TabularInline):
    model = TaskStatusHistory
    extra = 0
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


@admin.register(WorkspaceGroup)
class WorkspaceGroupAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "color",
        "is_active",
        "created_by",
        "created_at",
    )
    list_filter = (
        "is_active",
        "created_at",
    )
    search_fields = (
        "name",
        "description",
    )
    inlines = [
        WorkspaceMembershipInline,
    ]


@admin.register(WorkspaceMembership)
class WorkspaceMembershipAdmin(admin.ModelAdmin):
    list_display = (
        "group",
        "user",
        "role",
        "is_active",
        "created_at",
    )
    list_filter = (
        "role",
        "is_active",
        "created_at",
    )
    search_fields = (
        "group__name",
        "user__username",
        "user__first_name",
        "user__last_name",
    )


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "task_type",
        "status",
        "priority",
        "assigned_to",
        "group",
        "due_at",
        "is_important",
        "is_private",
        "created_at",
    )
    list_filter = (
        "status",
        "priority",
        "task_type",
        "group",
        "assigned_to",
        "is_important",
        "is_private",
        "created_at",
        "due_at",
    )
    search_fields = (
        "title",
        "description",
        "assigned_to__username",
        "assigned_to__first_name",
        "assigned_to__last_name",
        "group__name",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "completed_at",
    )
    inlines = [
        TaskCommentInline,
        TaskStatusHistoryInline,
    ]


@admin.register(TaskComment)
class TaskCommentAdmin(admin.ModelAdmin):
    list_display = (
        "task",
        "user",
        "created_at",
    )
    list_filter = (
        "created_at",
    )
    search_fields = (
        "task__title",
        "comment",
        "user__username",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )


@admin.register(TaskStatusHistory)
class TaskStatusHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "task",
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
        "task__title",
        "changed_by__username",
        "note",
    )
    readonly_fields = (
        "task",
        "changed_by",
        "old_status",
        "new_status",
        "note",
        "created_at",
    )


@admin.register(CalendarEvent)
class CalendarEventAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "event_type",
        "assigned_to",
        "group",
        "start_at",
        "end_at",
        "is_all_day",
        "created_at",
    )
    list_filter = (
        "event_type",
        "group",
        "assigned_to",
        "is_all_day",
        "start_at",
        "created_at",
    )
    search_fields = (
        "title",
        "description",
        "location",
        "assigned_to__username",
        "group__name",
    )
    filter_horizontal = (
        "participants",
    )


@admin.register(Reminder)
class ReminderAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "created_by",
        "user",
        "group",
        "task",
        "event",
        "remind_at",
        "status",
        "completed_at",
        "created_at",
    )
    list_filter = (
        "status",
        "group",
        "user",
        "remind_at",
        "completed_at",
        "created_at",
    )
    search_fields = (
        "title",
        "message",
        "user__username",
        "user__first_name",
        "user__last_name",
        "created_by__username",
        "group__name",
        "task__title",
        "event__title",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "completed_at",
    )