from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import serializers

from .models import (
    CalendarEvent,
    Reminder,
    Task,
    TaskComment,
    TaskStatusHistory,
    WorkspaceGroup,
    WorkspaceMembership,
)
from .permissions import (
    usuario_puede_completar_recordatorio,
    usuario_puede_completar_tarea,
    usuario_puede_dar_seguimiento_tarea,
    usuario_puede_editar_datos_evento,
    usuario_puede_editar_datos_recordatorio,
    usuario_puede_editar_datos_tarea,
)


def get_user_display_name(user):
    if not user:
        return ""

    full_name = user.get_full_name().strip()

    if full_name:
        return full_name

    return user.username


def get_request_user(serializer):
    request = serializer.context.get("request")

    if not request:
        return None

    return request.user


class WorkspaceMembershipSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    role_display = serializers.CharField(
        source="get_role_display",
        read_only=True,
    )
    group_name = serializers.CharField(
        source="group.name",
        read_only=True,
    )

    class Meta:
        model = WorkspaceMembership
        fields = [
            "id",
            "group",
            "group_name",
            "user",
            "user_name",
            "role",
            "role_display",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "group_name",
            "user_name",
            "role_display",
            "created_at",
            "updated_at",
        ]

    def get_user_name(self, obj):
        return get_user_display_name(obj.user)


class WorkspaceGroupSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    memberships = WorkspaceMembershipSerializer(
        many=True,
        read_only=True,
    )

    class Meta:
        model = WorkspaceGroup
        fields = [
            "id",
            "name",
            "description",
            "color",
            "is_active",
            "created_by",
            "created_by_name",
            "memberships",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_by_name",
            "memberships",
            "created_at",
            "updated_at",
        ]

    def get_created_by_name(self, obj):
        return get_user_display_name(obj.created_by)


class TaskCommentSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = TaskComment
        fields = [
            "id",
            "task",
            "user",
            "user_name",
            "comment",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "task",
            "user",
            "user_name",
            "created_at",
            "updated_at",
        ]

    def get_user_name(self, obj):
        return get_user_display_name(obj.user)


class TaskStatusHistorySerializer(serializers.ModelSerializer):
    changed_by_name = serializers.SerializerMethodField()
    old_status_display = serializers.SerializerMethodField()
    new_status_display = serializers.SerializerMethodField()

    class Meta:
        model = TaskStatusHistory
        fields = [
            "id",
            "task",
            "changed_by",
            "changed_by_name",
            "old_status",
            "old_status_display",
            "new_status",
            "new_status_display",
            "note",
            "created_at",
        ]
        read_only_fields = fields

    def get_changed_by_name(self, obj):
        return get_user_display_name(obj.changed_by)

    def get_old_status_display(self, obj):
        return dict(Task.STATUS_CHOICES).get(
            obj.old_status,
            obj.old_status,
        )

    def get_new_status_display(self, obj):
        return dict(Task.STATUS_CHOICES).get(
            obj.new_status,
            obj.new_status,
        )


class TaskSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    group_name = serializers.CharField(
        source="group.name",
        read_only=True,
    )
    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )
    priority_display = serializers.CharField(
        source="get_priority_display",
        read_only=True,
    )
    task_type_display = serializers.CharField(
        source="get_task_type_display",
        read_only=True,
    )
    is_overdue = serializers.BooleanField(read_only=True)
    comments = TaskCommentSerializer(
        many=True,
        read_only=True,
    )
    status_history = TaskStatusHistorySerializer(
        many=True,
        read_only=True,
    )
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    can_edit_details = serializers.SerializerMethodField()
    can_follow_up = serializers.SerializerMethodField()
    can_complete = serializers.SerializerMethodField()
    is_read_only = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "id",
            "title",
            "description",
            "task_type",
            "task_type_display",
            "status",
            "status_display",
            "priority",
            "priority_display",
            "group",
            "group_name",
            "created_by",
            "created_by_name",
            "assigned_to",
            "assigned_to_name",
            "start_at",
            "due_at",
            "reminder_at",
            "completed_at",
            "is_important",
            "is_private",
            "is_overdue",
            "related_contact_request",
            "comments",
            "status_history",
            "can_edit_details",
            "can_follow_up",
            "can_complete",
            "is_read_only",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_by_name",
            "assigned_to_name",
            "completed_at",
            "is_overdue",
            "comments",
            "status_history",
            "can_edit_details",
            "can_follow_up",
            "can_complete",
            "is_read_only",
            "created_at",
            "updated_at",
        ]

    def get_created_by_name(self, obj):
        return get_user_display_name(obj.created_by)

    def get_assigned_to_name(self, obj):
        return get_user_display_name(obj.assigned_to)

    def get_can_edit_details(self, obj):
        user = get_request_user(self)
        return usuario_puede_editar_datos_tarea(user, obj)

    def get_can_follow_up(self, obj):
        user = get_request_user(self)
        return usuario_puede_dar_seguimiento_tarea(user, obj)

    def get_can_complete(self, obj):
        user = get_request_user(self)
        return usuario_puede_completar_tarea(user, obj)

    def get_is_read_only(self, obj):
        return not self.get_can_edit_details(obj) and not self.get_can_follow_up(obj)


class TaskStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=Task.STATUS_CHOICES,
    )
    note = serializers.CharField(
        required=False,
        allow_blank=True,
    )


class TaskAddCommentSerializer(serializers.Serializer):
    comment = serializers.CharField()


class CalendarEventSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    group_name = serializers.CharField(
        source="group.name",
        read_only=True,
    )
    event_type_display = serializers.CharField(
        source="get_event_type_display",
        read_only=True,
    )
    participants = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        many=True,
        required=False,
    )
    participants_names = serializers.SerializerMethodField()
    can_edit_details = serializers.SerializerMethodField()
    is_read_only = serializers.SerializerMethodField()

    class Meta:
        model = CalendarEvent
        fields = [
            "id",
            "title",
            "description",
            "event_type",
            "event_type_display",
            "group",
            "group_name",
            "created_by",
            "created_by_name",
            "assigned_to",
            "assigned_to_name",
            "participants",
            "participants_names",
            "start_at",
            "end_at",
            "is_all_day",
            "location",
            "related_task",
            "related_contact_request",
            "can_edit_details",
            "is_read_only",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_by_name",
            "assigned_to_name",
            "participants_names",
            "can_edit_details",
            "is_read_only",
            "created_at",
            "updated_at",
        ]

    def get_created_by_name(self, obj):
        return get_user_display_name(obj.created_by)

    def get_assigned_to_name(self, obj):
        return get_user_display_name(obj.assigned_to)

    def get_participants_names(self, obj):
        return [get_user_display_name(user) for user in obj.participants.all()]

    def get_can_edit_details(self, obj):
        user = get_request_user(self)
        return usuario_puede_editar_datos_evento(user, obj)

    def get_is_read_only(self, obj):
        return not self.get_can_edit_details(obj)


class ReminderSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    assigned_to = serializers.PrimaryKeyRelatedField(
        source="user",
        queryset=User.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    assigned_to_name = serializers.SerializerMethodField()
    group_name = serializers.CharField(
        source="group.name",
        read_only=True,
    )
    task_title = serializers.CharField(
        source="task.title",
        read_only=True,
    )
    event_title = serializers.CharField(
        source="event.title",
        read_only=True,
    )
    description = serializers.CharField(
        source="message",
        required=False,
        allow_blank=True,
    )
    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )
    is_completed = serializers.BooleanField(
        required=False,
    )
    is_overdue = serializers.BooleanField(
        read_only=True,
    )
    can_edit_details = serializers.SerializerMethodField()
    can_complete = serializers.SerializerMethodField()
    is_read_only = serializers.SerializerMethodField()

    class Meta:
        model = Reminder
        fields = [
            "id",
            "created_by",
            "created_by_name",
            "user",
            "user_name",
            "assigned_to",
            "assigned_to_name",
            "group",
            "group_name",
            "task",
            "task_title",
            "event",
            "event_title",
            "title",
            "message",
            "description",
            "remind_at",
            "status",
            "status_display",
            "is_completed",
            "is_overdue",
            "can_edit_details",
            "can_complete",
            "is_read_only",
            "completed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_by_name",
            "user",
            "user_name",
            "assigned_to_name",
            "group_name",
            "task_title",
            "event_title",
            "status_display",
            "is_overdue",
            "can_edit_details",
            "can_complete",
            "is_read_only",
            "completed_at",
            "created_at",
            "updated_at",
        ]

    def get_user_name(self, obj):
        return get_user_display_name(obj.user)

    def get_created_by_name(self, obj):
        return get_user_display_name(obj.created_by)

    def get_assigned_to_name(self, obj):
        return get_user_display_name(obj.user)

    def get_can_edit_details(self, obj):
        user = get_request_user(self)
        return usuario_puede_editar_datos_recordatorio(user, obj)

    def get_can_complete(self, obj):
        user = get_request_user(self)
        return usuario_puede_completar_recordatorio(user, obj)

    def get_is_read_only(self, obj):
        return not self.get_can_edit_details(obj) and not self.get_can_complete(obj)

    def validate(self, attrs):
        task = attrs.get("task")
        event = attrs.get("event")

        if task and event:
            raise serializers.ValidationError({
                "event": "El recordatorio debe estar vinculado a una tarea o a un evento, no a ambos."
            })

        return attrs

    def create(self, validated_data):
        is_completed = validated_data.pop("is_completed", False)
        request = self.context.get("request")

        if not validated_data.get("user") and request:
            validated_data["user"] = request.user

        task = validated_data.get("task")
        event = validated_data.get("event")

        if not validated_data.get("group"):
            if task and task.group:
                validated_data["group"] = task.group

            if event and event.group:
                validated_data["group"] = event.group

        reminder = Reminder(**validated_data)

        if is_completed:
            reminder.mark_completed()

        reminder.save()

        return reminder

    def update(self, instance, validated_data):
        is_completed = validated_data.pop("is_completed", None)

        for field, value in validated_data.items():
            setattr(instance, field, value)

        if is_completed is True:
            instance.mark_completed()

        if is_completed is False:
            instance.reopen()

        if instance.status == "completed" and not instance.completed_at:
            instance.completed_at = timezone.now()

        if instance.status != "completed":
            instance.completed_at = None

        instance.save()

        return instance