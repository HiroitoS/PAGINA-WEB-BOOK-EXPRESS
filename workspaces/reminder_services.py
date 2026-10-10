from django.db import transaction
from django.utils import timezone

from .models import Reminder, Task
from .reminder_alerts import resolve_reminder_alert_notifications


TASK_REMINDER_SOURCE = "task"
CLOSED_TASK_STATUSES = {"completed", "cancelled"}


def get_primary_task_reminder(task):
    """
    Retorna el recordatorio principal que representa el recordatorio propio
    de una tarea.

    Los recordatorios manuales vinculados a la misma tarea permanecen
    independientes y no se pisan entre sí.
    """
    if not task or not task.pk:
        return None

    return (
        Reminder.objects
        .filter(
            task_id=task.pk,
            source=TASK_REMINDER_SOURCE,
        )
        .order_by("id")
        .first()
    )


def _update_task_mirror(task, reminder_at):
    """
    Mantiene Task.reminder_at como espejo temporal de compatibilidad.

    La fuente oficial es Reminder. Se conserva el campo de Task mientras el
    frontend antiguo y otros flujos terminan de migrar.
    """
    if not task or not task.pk:
        return

    if task.reminder_at == reminder_at:
        return

    Task.objects.filter(pk=task.pk).update(
        reminder_at=reminder_at,
    )
    task.reminder_at = reminder_at


@transaction.atomic
def sync_primary_task_reminder(task, *, actor=None):
    """
    Sincroniza el recordatorio principal desde una Task ya guardada.

    Reglas:
    - una tarea activa con reminder_at crea/actualiza un Reminder source=task;
    - el recordatorio siempre pertenece al responsable de la tarea;
    - una tarea cerrada conserva el Reminder como completado;
    - quitar reminder_at elimina únicamente el recordatorio principal,
      nunca los recordatorios manuales asociados a la tarea.
    """
    if not task or not task.pk:
        return None

    reminder = (
        Reminder.objects
        .select_for_update()
        .filter(
            task_id=task.pk,
            source=TASK_REMINDER_SOURCE,
        )
        .order_by("id")
        .first()
    )

    if task.status in CLOSED_TASK_STATUSES:
        if reminder and reminder.status != "completed":
            reminder.status = "completed"
            reminder.completed_at = timezone.now()
            reminder.save(
                update_fields=[
                    "status",
                    "completed_at",
                    "updated_at",
                ]
            )

        if reminder:
            resolve_reminder_alert_notifications(reminder)

        _update_task_mirror(task, None)
        return reminder

    if not task.reminder_at:
        # Conservar el historial de los avisos ya atendidos o descartados.
        if reminder and reminder.status in {"pending", "seen"}:
            resolve_reminder_alert_notifications(reminder)
            reminder.delete()
            reminder = None

        _update_task_mirror(task, None)
        return reminder

    if not task.assigned_to_id:
        raise ValueError(
            "La tarea debe tener un responsable antes de programar "
            "un recordatorio."
        )

    reminder_user = task.assigned_to
    reminder_group = task.group
    reminder_creator = actor or task.created_by or reminder_user

    if reminder:
        previous_user_id = reminder.user_id
        was_rescheduled = reminder.remind_at != task.reminder_at

        reminder.user = reminder_user
        reminder.group = reminder_group
        reminder.event = None
        reminder.title = task.title
        reminder.remind_at = task.reminder_at

        # Editar el título o responsable no debe reactivar un aviso atendido.
        if was_rescheduled:
            reminder.status = "pending"
            reminder.completed_at = None

        reminder.save(
            update_fields=[
                "user",
                "group",
                "event",
                "title",
                "remind_at",
                "status",
                "completed_at",
                "updated_at",
            ]
        )
        if was_rescheduled or previous_user_id != reminder.user_id:
            resolve_reminder_alert_notifications(reminder)
    else:
        reminder = Reminder.objects.create(
            created_by=reminder_creator,
            user=reminder_user,
            group=reminder_group,
            task=task,
            event=None,
            title=task.title,
            message="",
            remind_at=task.reminder_at,
            status="pending",
            source=TASK_REMINDER_SOURCE,
        )

    _update_task_mirror(
        task,
        reminder.remind_at
        if reminder.status not in {"completed", "dismissed"}
        else None,
    )
    return reminder


@transaction.atomic
def sync_task_mirror_from_reminder(reminder):
    """
    Refleja en Task.reminder_at un cambio hecho desde el módulo Recordatorios.

    Solo aplica al Reminder principal de la tarea. Los recordatorios manuales
    no modifican la planificación propia de la Task.
    """
    if (
        not reminder
        or reminder.source != TASK_REMINDER_SOURCE
        or not reminder.task_id
    ):
        return None

    task = Task.objects.select_for_update().get(
        pk=reminder.task_id,
    )

    # No reprogramar la tarea cerrada desde un recordatorio.
    if task.status in CLOSED_TASK_STATUSES:
        _update_task_mirror(task, None)
        return task

    if reminder.status in {"completed", "dismissed"}:
        reminder_at = None
    else:
        reminder_at = reminder.remind_at

    _update_task_mirror(task, reminder_at)
    return task


@transaction.atomic
def clear_task_mirror_for_reminder(reminder):
    """
    Limpia el espejo de Task antes de eliminar su recordatorio principal.
    """
    if (
        not reminder
        or reminder.source != TASK_REMINDER_SOURCE
        or not reminder.task_id
    ):
        return

    Task.objects.filter(pk=reminder.task_id).update(
        reminder_at=None,
    )
