"""API de recordatorios de ToDo.

Separada de workspaces.views para aislar las reglas de aviso, conservar
los contratos HTTP y facilitar las pruebas de regresión.
"""

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from .notification_events import notify_reminder_assigned
from .permissions import (
    EsUsuarioWorkspace,
    user_can_assign_to_other_user,
    usuario_es_miembro_activo,
    usuario_puede_completar_recordatorio,
    usuario_puede_editar_datos_recordatorio,
)
from .reminder_alerts import (
    resolve_reminder_alert_notifications,
    sync_reminder_alerts_for_user,
)
from .reminder_services import (
    clear_task_mirror_for_reminder,
    sync_task_mirror_from_reminder,
)
from .selectors import visible_reminders_queryset
from .serializers import ReminderSerializer


class WorkspaceReminderPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 200


class ReminderViewSet(viewsets.ModelViewSet):
    serializer_class = ReminderSerializer
    pagination_class = WorkspaceReminderPagination
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

        return queryset.order_by("status", "remind_at", "-created_at", "-id").distinct()

    @action(
        detail=False,
        methods=["post"],
        url_path="sync-alerts",
    )
    def sync_alerts(self, request):
        result = sync_reminder_alerts_for_user(request.user)

        return Response(
            result,
            status=status.HTTP_200_OK,
        )

    @transaction.atomic
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

        reminder = serializer.save(
            created_by=self.request.user,
            user=assigned_user,
            group=group,
        )

        notify_reminder_assigned(
            reminder,
            actor=self.request.user,
        )

    @transaction.atomic
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

            updated_reminder = serializer.save()
            sync_task_mirror_from_reminder(updated_reminder)
            resolve_reminder_alert_notifications(updated_reminder)
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

        old_user = reminder.user
        old_user_id = reminder.user_id
        old_remind_at = reminder.remind_at

        save_kwargs = {}
        if reminder.source == "task" and reminder.task_id:
            save_kwargs = {
                "user": reminder.task.assigned_to,
                "group": reminder.task.group,
                "task": reminder.task,
                "event": None,
                "source": "task",
            }

        updated_reminder = serializer.save(**save_kwargs)
        sync_task_mirror_from_reminder(updated_reminder)

        if (
            updated_reminder.user_id != old_user_id
            or updated_reminder.remind_at != old_remind_at
        ):
            resolve_reminder_alert_notifications(updated_reminder)

        notify_reminder_assigned(
            updated_reminder,
            actor=self.request.user,
            previous_user=old_user,
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        if not usuario_puede_editar_datos_recordatorio(
            self.request.user,
            instance,
        ):
            raise PermissionDenied(
                "No tienes permiso para eliminar este recordatorio."
            )

        if instance.crm_links.exists():
            raise ValidationError({
                "detail": (
                    "Este recordatorio está vinculado al CRM y debe "
                    "conservarse. Puedes marcarlo como completado."
                ),
            })

        resolve_reminder_alert_notifications(instance)
        clear_task_mirror_for_reminder(instance)
        instance.delete()
