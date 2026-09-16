import logging
from functools import partial

from django.db import transaction

from notifications.services import (
    create_notification,
    create_notifications_for_users,
    resolve_notifications_for_source,
)


logger = logging.getLogger(__name__)


def _run_notification_callback(callback):
    try:
        callback()
    except Exception:
        logger.exception(
            "No se pudo crear una notificación de workspaces."
        )


def _schedule(callback):
    """
    Ejecuta la notificación después del commit de la operación principal.

    Si el canal de notificaciones falla, no revierte la acción de negocio
    (tarea, evento, recordatorio, etc.). En el futuro este punto puede
    migrarse a una cola de trabajos sin tocar los ViewSets.
    """
    transaction.on_commit(
        partial(_run_notification_callback, callback)
    )


def _display_name(user):
    if not user:
        return ""

    full_name = user.get_full_name().strip()
    return full_name or user.username


def notify_group_membership_created(membership, actor):
    recipient = membership.user

    if (
        not membership.is_active
        or not recipient
        or recipient.id == getattr(actor, "id", None)
    ):
        return

    def callback():
        create_notification(
            recipient=recipient,
            actor=actor,
            title="Te agregaron a un grupo de trabajo",
            message=(
                f"Ahora perteneces al grupo "
                f"\"{membership.group.name}\"."
            ),
            event_type="workspace.group_member_added",
            module="todo",
            severity="info",
            link="/admin/workspace/groups",
            source_app="workspaces",
            source_model="WorkspaceMembership",
            source_id=membership.id,
            metadata={
                "group_id": membership.group_id,
                "group_name": membership.group.name,
                "membership_role": membership.role,
            },
            dedup_key=(
                f"workspace:membership:{membership.id}:created"
            ),
        )

    _schedule(callback)


def notify_task_assigned(task, actor, previous_assignee=None):
    recipient = task.assigned_to

    if not recipient:
        return

    if recipient.id == getattr(actor, "id", None):
        return

    if (
        previous_assignee
        and previous_assignee.id == recipient.id
    ):
        return

    is_reassignment = previous_assignee is not None
    actor_name = _display_name(actor)

    def callback():
        create_notification(
            recipient=recipient,
            actor=actor,
            title=(
                "Tarea reasignada"
                if is_reassignment
                else "Nueva tarea asignada"
            ),
            message=(
                f"{actor_name} te asignó la tarea "
                f"\"{task.title}\"."
            ),
            event_type="workspace.task_assigned",
            module="todo",
            severity=(
                "warning"
                if task.priority in ["high", "urgent"]
                else "info"
            ),
            link=f"/admin/workspace/tasks?task={task.id}&tab=info",
            source_app="workspaces",
            source_model="Task",
            source_id=task.id,
            metadata={
                "task_id": task.id,
                "task_title": task.title,
                "priority": task.priority,
                "group_id": task.group_id,
            },
            dedup_key=(
                f"workspace:task:{task.id}:assigned:"
                f"{recipient.id}:{task.updated_at.isoformat()}"
            ),
        )

    _schedule(callback)


def notify_task_comment_created(comment, actor):
    task = comment.task

    recipients = [
        task.created_by,
        task.assigned_to,
    ]

    actor_name = _display_name(actor)

    def callback():
        create_notifications_for_users(
            recipients=recipients,
            exclude_user=actor,
            actor=actor,
            title="Nueva gestión en una tarea",
            message=(
                f"{actor_name} registró una gestión en "
                f"\"{task.title}\"."
            ),
            event_type="workspace.task_comment_added",
            module="todo",
            severity="info",
            link=(
                f"/admin/workspace/tasks?task={task.id}"
                f"&tab=history&comment={comment.id}"
            ),
            source_app="workspaces",
            source_model="TaskComment",
            source_id=comment.id,
            metadata={
                "task_id": task.id,
                "task_title": task.title,
                "comment_id": comment.id,
                "action_type": comment.action_type,
            },
            dedup_key_prefix=(
                f"workspace:task_comment:{comment.id}"
            ),
        )

    _schedule(callback)


def notify_event_assigned(event, actor, previous_assignee=None):
    recipient = event.assigned_to

    if not recipient:
        return

    if recipient.id == getattr(actor, "id", None):
        return

    if (
        previous_assignee
        and previous_assignee.id == recipient.id
    ):
        return

    actor_name = _display_name(actor)
    is_reassignment = previous_assignee is not None

    def callback():
        create_notification(
            recipient=recipient,
            actor=actor,
            title=(
                "Evento reasignado"
                if is_reassignment
                else "Nuevo evento asignado"
            ),
            message=(
                f"{actor_name} te asignó el evento "
                f"\"{event.title}\"."
            ),
            event_type="workspace.event_assigned",
            module="todo",
            severity="info",
            link="/admin/workspace/calendar",
            source_app="workspaces",
            source_model="CalendarEvent",
            source_id=event.id,
            metadata={
                "event_id": event.id,
                "event_title": event.title,
                "event_type": event.event_type,
                "start_at": event.start_at.isoformat(),
                "group_id": event.group_id,
            },
            dedup_key=(
                f"workspace:event:{event.id}:assigned:"
                f"{recipient.id}:{event.updated_at.isoformat()}"
            ),
        )

    _schedule(callback)


def notify_reminder_assigned(
    reminder,
    actor,
    previous_user=None,
):
    recipient = reminder.user

    if not recipient:
        return

    if recipient.id == getattr(actor, "id", None):
        return

    if previous_user and previous_user.id == recipient.id:
        return

    actor_name = _display_name(actor)
    is_reassignment = previous_user is not None

    def callback():
        create_notification(
            recipient=recipient,
            actor=actor,
            title=(
                "Recordatorio reasignado"
                if is_reassignment
                else "Nuevo recordatorio asignado"
            ),
            message=(
                f"{actor_name} creó el recordatorio "
                f"\"{reminder.title}\" para ti."
            ),
            event_type="workspace.reminder_assigned",
            module="todo",
            severity="info",
            link="/admin/workspace/reminders",
            source_app="workspaces",
            source_model="Reminder",
            source_id=reminder.id,
            metadata={
                "reminder_id": reminder.id,
                "reminder_title": reminder.title,
                "remind_at": reminder.remind_at.isoformat(),
                "group_id": reminder.group_id,
                "task_id": reminder.task_id,
                "event_id": reminder.event_id,
            },
            dedup_key=(
                f"workspace:reminder:{reminder.id}:assigned:"
                f"{recipient.id}:{reminder.updated_at.isoformat()}"
            ),
        )

    _schedule(callback)


def resolve_task_notifications(task):
    """
    Cierra avisos pendientes relacionados con una tarea terminada/cancelada.

    El historial permanece disponible; solo deja de contarse como pendiente.
    """
    def callback():
        resolve_notifications_for_source(
            source_app="workspaces",
            source_model="Task",
            source_id=task.id,
            related_metadata={"task_id": task.id},
        )

    _schedule(callback)


def notify_task_reopened(task, actor):
    """
    Informa la reapertura sin revivir notificaciones históricas ya resueltas.
    """
    recipients = [
        task.created_by,
        task.assigned_to,
    ]

    actor_name = _display_name(actor)

    def callback():
        create_notifications_for_users(
            recipients=recipients,
            exclude_user=actor,
            actor=actor,
            title="Tarea reabierta",
            message=(
                f"{actor_name} reabrió la tarea "
                f"\"{task.title}\"."
            ),
            event_type="workspace.task_reopened",
            module="todo",
            severity="warning",
            link=(
                f"/admin/workspace/tasks?task={task.id}"
                f"&tab=history&event=reopened"
                f"&at={int(task.updated_at.timestamp())}"
            ),
            source_app="workspaces",
            source_model="Task",
            source_id=task.id,
            metadata={
                "task_id": task.id,
                "task_title": task.title,
                "status": task.status,
            },
            dedup_key_prefix=(
                f"workspace:task:{task.id}:reopened:"
                f"{task.updated_at.isoformat()}"
            ),
        )

    _schedule(callback)
