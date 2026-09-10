from datetime import datetime, time

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import usuario_es_administrador

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
    EsUsuarioWorkspace,
    usuario_es_miembro_activo,
    usuario_puede_completar_recordatorio,
    usuario_puede_completar_tarea,
    usuario_puede_dar_seguimiento_tarea,
    usuario_puede_editar_datos_evento,
    usuario_puede_editar_datos_recordatorio,
    usuario_puede_editar_datos_tarea,
    usuario_puede_gestionar_grupo,
    usuario_puede_ver_evento,
    usuario_puede_ver_recordatorio,
    usuario_puede_ver_tarea,
)
from .serializers import (
    CalendarEventSerializer,
    ReminderSerializer,
    TaskAddCommentSerializer,
    TaskCommentSerializer,
    TaskSerializer,
    TaskStatusHistorySerializer,
    TaskStatusUpdateSerializer,
    WorkspaceGroupSerializer,
    WorkspaceMembershipSerializer,
)


def make_aware_if_needed(value):
    if timezone.is_naive(value):
        return timezone.make_aware(value, timezone.get_current_timezone())

    return value


def parse_range_datetime(value, default_value):
    if not value:
        return default_value

    parsed_datetime = parse_datetime(value)

    if parsed_datetime:
        return make_aware_if_needed(parsed_datetime)

    parsed_date = parse_date(value)

    if parsed_date:
        return make_aware_if_needed(datetime.combine(parsed_date, time.min))

    return default_value


def get_user_group_ids(user):
    return WorkspaceMembership.objects.filter(
        user=user,
        is_active=True,
        group__is_active=True,
    ).values_list("group_id", flat=True)


def user_can_assign_to_other_user(request_user, assigned_user, group=None):
    if not assigned_user:
        return True

    if assigned_user.id == request_user.id:
        return True

    if usuario_es_administrador(request_user):
        return True

    if group and usuario_puede_gestionar_grupo(request_user, group):
        return True

    return False


def visible_groups_queryset(user):
    queryset = WorkspaceGroup.objects.prefetch_related(
        "memberships",
        "memberships__user",
    ).all()

    if usuario_es_administrador(user):
        return queryset

    return queryset.filter(
        Q(created_by=user)
        | Q(memberships__user=user, memberships__is_active=True)
    ).distinct()


def visible_tasks_queryset(user):
    queryset = (
        Task.objects.select_related(
            "group",
            "created_by",
            "assigned_to",
            "related_contact_request",
        )
        .prefetch_related(
            "comments",
            "comments__user",
            "status_history",
            "status_history__changed_by",
        )
        .all()
    )

    if usuario_es_administrador(user):
        return queryset

    group_ids = get_user_group_ids(user)

    return queryset.filter(
        Q(created_by=user)
        | Q(assigned_to=user)
        | Q(group_id__in=group_ids)
    ).distinct()


def visible_events_queryset(user):
    queryset = (
        CalendarEvent.objects.select_related(
            "group",
            "created_by",
            "assigned_to",
            "related_task",
            "related_contact_request",
        )
        .prefetch_related("participants")
        .all()
    )

    if usuario_es_administrador(user):
        return queryset

    group_ids = get_user_group_ids(user)

    return queryset.filter(
        Q(created_by=user)
        | Q(assigned_to=user)
        | Q(participants=user)
        | Q(group_id__in=group_ids)
    ).distinct()


def visible_reminders_queryset(user):
    queryset = (
        Reminder.objects.select_related(
            "created_by",
            "user",
            "group",
            "task",
            "task__group",
            "event",
            "event__group",
        )
        .all()
    )

    if usuario_es_administrador(user):
        return queryset

    group_ids = get_user_group_ids(user)

    return queryset.filter(
        Q(created_by=user)
        | Q(user=user)
        | Q(group_id__in=group_ids)
        | Q(task__group_id__in=group_ids)
        | Q(event__group_id__in=group_ids)
    ).distinct()


def get_display_name(user):
    if not user:
        return ""

    full_name = user.get_full_name().strip()

    if full_name:
        return full_name

    return user.username


class WorkspaceGroupViewSet(viewsets.ModelViewSet):
    serializer_class = WorkspaceGroupSerializer
    permission_classes = [EsUsuarioWorkspace]

    def get_queryset(self):
        queryset = visible_groups_queryset(self.request.user).order_by("name")
        search = self.request.query_params.get("search")
        is_active = self.request.query_params.get("is_active")

        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(description__icontains=search)
            )

        if is_active == "true":
            queryset = queryset.filter(is_active=True)

        if is_active == "false":
            queryset = queryset.filter(is_active=False)

        return queryset.distinct()

    def perform_create(self, serializer):
        if not usuario_es_administrador(self.request.user):
            raise PermissionDenied(
                "Solo un administrador puede crear grupos de trabajo."
            )

        group = serializer.save(created_by=self.request.user)

        WorkspaceMembership.objects.get_or_create(
            group=group,
            user=self.request.user,
            defaults={
                "role": "owner",
                "is_active": True,
            },
        )

    def perform_update(self, serializer):
        group = self.get_object()

        if not usuario_puede_gestionar_grupo(self.request.user, group):
            raise PermissionDenied(
                "No tienes permiso para modificar este grupo."
            )

        serializer.save()


class WorkspaceMembershipViewSet(viewsets.ModelViewSet):
    serializer_class = WorkspaceMembershipSerializer
    permission_classes = [EsUsuarioWorkspace]

    def get_queryset(self):
        groups = visible_groups_queryset(self.request.user)

        return (
            WorkspaceMembership.objects.select_related("group", "user")
            .filter(group__in=groups)
            .order_by("group__name", "user__username")
        )

    def perform_create(self, serializer):
        group = serializer.validated_data["group"]

        if not usuario_puede_gestionar_grupo(self.request.user, group):
            raise PermissionDenied(
                "No tienes permiso para agregar miembros a este grupo."
            )

        serializer.save()

    def perform_update(self, serializer):
        membership = self.get_object()

        if not usuario_puede_gestionar_grupo(
            self.request.user,
            membership.group,
        ):
            raise PermissionDenied(
                "No tienes permiso para modificar este miembro."
            )

        serializer.save()

    def perform_destroy(self, instance):
        if not usuario_puede_gestionar_grupo(
            self.request.user,
            instance.group,
        ):
            raise PermissionDenied(
                "No tienes permiso para eliminar este miembro."
            )

        instance.delete()


class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    permission_classes = [EsUsuarioWorkspace]

    def get_queryset(self):
        queryset = visible_tasks_queryset(self.request.user)

        status_param = self.request.query_params.get("status")
        priority = self.request.query_params.get("priority")
        task_type = self.request.query_params.get("task_type")
        group = self.request.query_params.get("group")
        assigned_to = self.request.query_params.get("assigned_to")
        search = self.request.query_params.get("search")
        due = self.request.query_params.get("due")
        ordering = self.request.query_params.get("ordering")

        if status_param:
            queryset = queryset.filter(status=status_param)

        if priority:
            queryset = queryset.filter(priority=priority)

        if task_type:
            queryset = queryset.filter(task_type=task_type)

        if group:
            queryset = queryset.filter(group_id=group)

        if assigned_to:
            queryset = queryset.filter(assigned_to_id=assigned_to)

        today = timezone.localdate()
        now = timezone.now()

        if due == "today":
            queryset = queryset.filter(due_at__date=today)

        if due == "overdue":
            queryset = queryset.filter(
                due_at__lt=now,
            ).exclude(
                status__in=["completed", "cancelled"],
            )

        if due == "upcoming":
            queryset = queryset.filter(
                due_at__gt=now,
            ).exclude(
                status__in=["completed", "cancelled"],
            )

        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(description__icontains=search)
                | Q(group__name__icontains=search)
                | Q(assigned_to__username__icontains=search)
                | Q(assigned_to__first_name__icontains=search)
                | Q(assigned_to__last_name__icontains=search)
            )

        if ordering in ["due_at", "-due_at", "created_at", "-created_at", "priority"]:
            return queryset.order_by(ordering).distinct()

        return queryset.order_by("status", "due_at", "-created_at").distinct()

    def perform_create(self, serializer):
        assigned_to = serializer.validated_data.get("assigned_to")

        if not assigned_to:
            assigned_to = self.request.user

        group = serializer.validated_data.get("group")

        if group and not usuario_es_miembro_activo(self.request.user, group):
            raise PermissionDenied(
                "No perteneces a este grupo de trabajo."
            )

        if not user_can_assign_to_other_user(self.request.user, assigned_to, group):
            raise PermissionDenied(
                "No tienes permiso para asignar tareas a otro usuario."
            )

        serializer.save(
            created_by=self.request.user,
            assigned_to=assigned_to,
        )

    def perform_update(self, serializer):
        task = self.get_object()

        if not usuario_puede_editar_datos_tarea(self.request.user, task):
            raise PermissionDenied(
                "No tienes permiso para modificar esta tarea."
            )

        assigned_to = serializer.validated_data.get("assigned_to", task.assigned_to)
        group = serializer.validated_data.get("group", task.group)

        if group and not usuario_es_miembro_activo(self.request.user, group):
            raise PermissionDenied(
                "No perteneces a este grupo de trabajo."
            )

        if assigned_to and not user_can_assign_to_other_user(
            self.request.user,
            assigned_to,
            group,
        ):
            raise PermissionDenied(
                "No tienes permiso para asignar tareas a otro usuario."
            )

        old_status = task.status
        updated_task = serializer.save()

        if old_status != updated_task.status:
            self._register_status_history(
                task=updated_task,
                old_status=old_status,
                new_status=updated_task.status,
                note="",
            )

            self._update_completed_at(updated_task)

    def _update_completed_at(self, task):
        if task.status == "completed":
            task.completed_at = timezone.now()
        elif task.status != "completed":
            task.completed_at = None

        task.save(
            update_fields=[
                "completed_at",
                "updated_at",
            ]
        )

    def _register_status_history(
        self,
        task,
        old_status,
        new_status,
        note="",
    ):
        TaskStatusHistory.objects.create(
            task=task,
            changed_by=self.request.user,
            old_status=old_status or "",
            new_status=new_status,
            note=note,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="change-status",
    )
    def change_status(self, request, pk=None):
        task = self.get_object()

        if not usuario_puede_dar_seguimiento_tarea(request.user, task):
            raise PermissionDenied(
                "No tienes permiso para cambiar el estado de esta tarea."
            )

        serializer = TaskStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        old_status = task.status
        new_status = serializer.validated_data["status"]
        note = serializer.validated_data.get("note", "")

        if old_status == new_status:
            return Response(
                {"detail": "La tarea ya se encuentra en ese estado."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        task.status = new_status

        if new_status == "completed":
            task.completed_at = timezone.now()
        else:
            task.completed_at = None

        task.save(
            update_fields=[
                "status",
                "completed_at",
                "updated_at",
            ]
        )

        self._register_status_history(
            task=task,
            old_status=old_status,
            new_status=new_status,
            note=note,
        )

        response_serializer = self.get_serializer(task)

        return Response(response_serializer.data)

    @action(
        detail=True,
        methods=["post"],
        url_path="add-comment",
    )
    def add_comment(self, request, pk=None):
        task = self.get_object()

        if not usuario_puede_dar_seguimiento_tarea(request.user, task):
            raise PermissionDenied(
                "No tienes permiso para comentar esta tarea."
            )

        serializer = TaskAddCommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        comment = TaskComment.objects.create(
            task=task,
            user=request.user,
            comment=serializer.validated_data["comment"],
        )

        response_serializer = TaskCommentSerializer(comment)

        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["get"],
        url_path="comments",
    )
    def comments(self, request, pk=None):
        task = self.get_object()

        if not usuario_puede_ver_tarea(request.user, task):
            raise PermissionDenied(
                "No tienes permiso para ver esta tarea."
            )

        comments = task.comments.select_related("user").all()
        serializer = TaskCommentSerializer(comments, many=True)

        return Response(serializer.data)

    @action(
        detail=True,
        methods=["get"],
        url_path="history",
    )
    def history(self, request, pk=None):
        task = self.get_object()

        if not usuario_puede_ver_tarea(request.user, task):
            raise PermissionDenied(
                "No tienes permiso para ver esta tarea."
            )

        history = task.status_history.select_related("changed_by").all()
        serializer = TaskStatusHistorySerializer(history, many=True)

        return Response(serializer.data)


class CalendarEventViewSet(viewsets.ModelViewSet):
    serializer_class = CalendarEventSerializer
    permission_classes = [EsUsuarioWorkspace]

    def get_queryset(self):
        queryset = visible_events_queryset(self.request.user)

        event_type = self.request.query_params.get("event_type")
        group = self.request.query_params.get("group")
        assigned_to = self.request.query_params.get("assigned_to")
        search = self.request.query_params.get("search")
        start = self.request.query_params.get("start")
        end = self.request.query_params.get("end")

        if event_type:
            queryset = queryset.filter(event_type=event_type)

        if group:
            queryset = queryset.filter(group_id=group)

        if assigned_to:
            queryset = queryset.filter(assigned_to_id=assigned_to)

        if start:
            start_at = parse_range_datetime(start, None)

            if start_at:
                queryset = queryset.filter(start_at__gte=start_at)

        if end:
            end_at = parse_range_datetime(end, None)

            if end_at:
                queryset = queryset.filter(start_at__lte=end_at)

        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(description__icontains=search)
                | Q(location__icontains=search)
                | Q(group__name__icontains=search)
            )

        return queryset.order_by("start_at").distinct()

    def perform_create(self, serializer):
        assigned_to = serializer.validated_data.get("assigned_to")

        if not assigned_to:
            assigned_to = self.request.user

        group = serializer.validated_data.get("group")

        if group and not usuario_es_miembro_activo(self.request.user, group):
            raise PermissionDenied(
                "No perteneces a este grupo de trabajo."
            )

        if not user_can_assign_to_other_user(self.request.user, assigned_to, group):
            raise PermissionDenied(
                "No tienes permiso para asignar eventos a otro usuario."
            )

        serializer.save(
            created_by=self.request.user,
            assigned_to=assigned_to,
        )

    def perform_update(self, serializer):
        event = self.get_object()

        if not usuario_puede_editar_datos_evento(self.request.user, event):
            raise PermissionDenied(
                "No tienes permiso para modificar este evento."
            )

        assigned_to = serializer.validated_data.get("assigned_to", event.assigned_to)
        group = serializer.validated_data.get("group", event.group)

        if group and not usuario_es_miembro_activo(self.request.user, group):
            raise PermissionDenied(
                "No perteneces a este grupo de trabajo."
            )

        if assigned_to and not user_can_assign_to_other_user(
            self.request.user,
            assigned_to,
            group,
        ):
            raise PermissionDenied(
                "No tienes permiso para asignar eventos a otro usuario."
            )

        serializer.save()


class ReminderViewSet(viewsets.ModelViewSet):
    serializer_class = ReminderSerializer
    permission_classes = [EsUsuarioWorkspace]

    def get_queryset(self):
        queryset = visible_reminders_queryset(self.request.user)

        reminder_status = self.request.query_params.get("status")
        scope = self.request.query_params.get("scope")
        group = self.request.query_params.get("group")
        assigned_to = self.request.query_params.get("assigned_to")
        user = self.request.query_params.get("user")
        search = self.request.query_params.get("search")
        is_completed = self.request.query_params.get("is_completed")
        now = timezone.now()

        if reminder_status:
            queryset = queryset.filter(status=reminder_status)

        if group:
            queryset = queryset.filter(group_id=group)

        if assigned_to:
            queryset = queryset.filter(user_id=assigned_to)

        if user:
            queryset = queryset.filter(user_id=user)

        if is_completed == "true":
            queryset = queryset.filter(status="completed")

        if is_completed == "false":
            queryset = queryset.exclude(status="completed")

        if scope == "overdue":
            queryset = queryset.filter(
                remind_at__lt=now,
                status="pending",
            )

        if scope == "upcoming":
            queryset = queryset.filter(
                remind_at__gte=now,
                status="pending",
            )

        if scope == "today":
            queryset = queryset.filter(
                remind_at__date=timezone.localdate(),
                status="pending",
            )

        if scope == "completed":
            queryset = queryset.filter(status="completed")

        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(message__icontains=search)
                | Q(group__name__icontains=search)
                | Q(user__username__icontains=search)
                | Q(user__first_name__icontains=search)
                | Q(user__last_name__icontains=search)
            )

        return queryset.order_by("status", "remind_at", "-created_at").distinct()

    def perform_create(self, serializer):
        assigned_user = serializer.validated_data.get("user")
        group = serializer.validated_data.get("group")
        task = serializer.validated_data.get("task")
        event = serializer.validated_data.get("event")

        if not assigned_user:
            assigned_user = self.request.user

        if not group:
            if task and task.group:
                group = task.group

            if event and event.group:
                group = event.group

        if group and not usuario_es_miembro_activo(self.request.user, group):
            raise PermissionDenied(
                "No perteneces a este grupo de trabajo."
            )

        if not user_can_assign_to_other_user(self.request.user, assigned_user, group):
            raise PermissionDenied(
                "No tienes permiso para asignar recordatorios a otro usuario."
            )

        serializer.save(
            created_by=self.request.user,
            user=assigned_user,
            group=group,
        )

    def perform_update(self, serializer):
        reminder = self.get_object()
        incoming_keys = set(self.request.data.keys())

        completion_keys = {"is_completed", "status", "completed_at"}
        only_completion_update = bool(incoming_keys) and incoming_keys.issubset(
            completion_keys,
        )

        if only_completion_update:
            if not usuario_puede_completar_recordatorio(self.request.user, reminder):
                raise PermissionDenied(
                    "No tienes permiso para completar este recordatorio."
                )

            serializer.save()
            return

        if not usuario_puede_editar_datos_recordatorio(self.request.user, reminder):
            raise PermissionDenied(
                "No tienes permiso para modificar este recordatorio."
            )

        assigned_user = serializer.validated_data.get("user", reminder.user)
        group = serializer.validated_data.get("group", reminder.group)

        if group and not usuario_es_miembro_activo(self.request.user, group):
            raise PermissionDenied(
                "No perteneces a este grupo de trabajo."
            )

        if not user_can_assign_to_other_user(self.request.user, assigned_user, group):
            raise PermissionDenied(
                "No tienes permiso para asignar recordatorios a otro usuario."
            )

        serializer.save()


class WorkspaceSummaryAPIView(APIView):
    permission_classes = [EsUsuarioWorkspace]

    def get(self, request):
        now = timezone.now()
        today = timezone.localdate()

        tasks = visible_tasks_queryset(request.user)
        events = visible_events_queryset(request.user)
        reminders = visible_reminders_queryset(request.user)

        active_tasks = tasks.exclude(
            status__in=["completed", "cancelled"],
        )

        data = {
            "my_pending_tasks": active_tasks.filter(status="pending").count(),
            "my_in_progress_tasks": active_tasks.filter(status="in_progress").count(),
            "my_due_today": active_tasks.filter(due_at__date=today).count(),
            "my_overdue": active_tasks.filter(due_at__lt=now).count(),
            "my_upcoming_events": events.filter(start_at__gte=now).count(),
            "my_pending_reminders": reminders.filter(status="pending").count(),
            "my_overdue_reminders": reminders.filter(
                remind_at__lt=now,
                status="pending",
            ).count(),
            "my_today_reminders": reminders.filter(
                remind_at__date=today,
                status="pending",
            ).count(),
            "groups_count": visible_groups_queryset(request.user).filter(
                is_active=True,
            ).count(),
        }

        return Response(data)


class WorkspaceCalendarAPIView(APIView):
    permission_classes = [EsUsuarioWorkspace]

    def get(self, request):
        now = timezone.now()

        start = parse_range_datetime(
            request.query_params.get("start"),
            now - timezone.timedelta(days=30),
        )
        end = parse_range_datetime(
            request.query_params.get("end"),
            now + timezone.timedelta(days=30),
        )
        group = request.query_params.get("group")

        tasks = visible_tasks_queryset(request.user).filter(
            Q(due_at__range=(start, end))
            | Q(start_at__range=(start, end))
            | Q(reminder_at__range=(start, end))
        ).exclude(
            status__in=["completed", "cancelled"],
        )

        events = visible_events_queryset(request.user).filter(
            start_at__range=(start, end),
        )

        reminders = visible_reminders_queryset(request.user).filter(
            remind_at__range=(start, end),
        ).exclude(
            status="completed",
        )

        if group:
            tasks = tasks.filter(group_id=group)
            events = events.filter(group_id=group)
            reminders = reminders.filter(group_id=group)

        calendar_items = []

        for task in tasks:
            can_edit_details = usuario_puede_editar_datos_tarea(request.user, task)
            can_follow_up = usuario_puede_dar_seguimiento_tarea(request.user, task)
            can_complete = usuario_puede_completar_tarea(request.user, task)
            is_read_only = not can_edit_details and not can_follow_up

            if task.due_at:
                calendar_items.append({
                    "id": f"task-{task.id}",
                    "real_id": task.id,
                    "task_id": task.id,
                    "type": "task",
                    "title": task.title,
                    "description": task.description,
                    "start": task.due_at,
                    "end": task.due_at,
                    "status": task.status,
                    "status_display": task.get_status_display(),
                    "priority": task.priority,
                    "priority_display": task.get_priority_display(),
                    "group": task.group_id,
                    "group_name": task.group.name if task.group else "",
                    "assigned_to": task.assigned_to_id,
                    "assigned_to_name": get_display_name(task.assigned_to),
                    "is_overdue": task.is_overdue,
                    "completed_at": task.completed_at,
                    "can_edit_details": can_edit_details,
                    "can_follow_up": can_follow_up,
                    "can_complete": can_complete,
                    "is_read_only": is_read_only,
                })

            if task.reminder_at:
                calendar_items.append({
                    "id": f"task-reminder-{task.id}",
                    "real_id": task.id,
                    "task_id": task.id,
                    "type": "task_reminder",
                    "title": f"Recordatorio: {task.title}",
                    "description": task.description,
                    "start": task.reminder_at,
                    "end": task.reminder_at,
                    "status": task.status,
                    "status_display": task.get_status_display(),
                    "priority": task.priority,
                    "priority_display": task.get_priority_display(),
                    "group": task.group_id,
                    "group_name": task.group.name if task.group else "",
                    "assigned_to": task.assigned_to_id,
                    "assigned_to_name": get_display_name(task.assigned_to),
                    "is_overdue": task.is_overdue,
                    "completed_at": task.completed_at,
                    "can_edit_details": can_edit_details,
                    "can_follow_up": can_follow_up,
                    "can_complete": can_complete,
                    "is_read_only": is_read_only,
                })

        for event in events:
            can_edit_details = usuario_puede_editar_datos_evento(request.user, event)
            is_read_only = not can_edit_details

            calendar_items.append({
                "id": f"event-{event.id}",
                "real_id": event.id,
                "event_id": event.id,
                "type": "event",
                "title": event.title,
                "description": event.description,
                "start": event.start_at,
                "end": event.end_at,
                "status": "scheduled",
                "status_display": "Programado",
                "priority": "",
                "priority_display": "",
                "group": event.group_id,
                "group_name": event.group.name if event.group else "",
                "assigned_to": event.assigned_to_id,
                "assigned_to_name": get_display_name(event.assigned_to),
                "event_type": event.event_type,
                "event_type_display": event.get_event_type_display(),
                "is_all_day": event.is_all_day,
                "location": event.location,
                "can_edit_details": can_edit_details,
                "can_follow_up": False,
                "can_complete": False,
                "is_read_only": is_read_only,
            })

        for reminder in reminders:
            can_edit_details = usuario_puede_editar_datos_recordatorio(
                request.user,
                reminder,
            )
            can_complete = usuario_puede_completar_recordatorio(
                request.user,
                reminder,
            )
            is_read_only = not can_edit_details and not can_complete

            calendar_items.append({
                "id": f"reminder-{reminder.id}",
                "real_id": reminder.id,
                "reminder_id": reminder.id,
                "type": "reminder",
                "title": reminder.title,
                "description": reminder.message,
                "message": reminder.message,
                "start": reminder.remind_at,
                "end": reminder.remind_at,
                "status": reminder.status,
                "status_display": reminder.get_status_display(),
                "priority": "",
                "priority_display": "",
                "group": reminder.group_id,
                "group_name": reminder.group.name if reminder.group else "",
                "assigned_to": reminder.user_id,
                "assigned_to_name": get_display_name(reminder.user),
                "task": reminder.task_id,
                "event": reminder.event_id,
                "is_completed": reminder.is_completed,
                "is_overdue": reminder.is_overdue,
                "completed_at": reminder.completed_at,
                "can_edit_details": can_edit_details,
                "can_follow_up": False,
                "can_complete": can_complete,
                "is_read_only": is_read_only,
            })

        calendar_items.sort(key=lambda item: item["start"])

        return Response(calendar_items)