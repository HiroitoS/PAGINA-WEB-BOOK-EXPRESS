from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.permissions import usuario_es_administrador

from .models import CalendarEvent, Reminder, Task
from .notification_events import (
    notify_event_assigned,
    notify_reminder_assigned,
    notify_task_assigned,
)
from .permissions import (
    usuario_es_miembro_activo,
    usuario_puede_asignar_trabajo,
    usuario_puede_gestionar_grupo,
)


class WorkspaceOperationError(ValidationError):
    pass


def user_can_assign_to_other_user(actor, assigned_user, group=None):
    if not actor or not actor.is_authenticated:
        return False

    if not assigned_user:
        return True

    if assigned_user.id == actor.id:
        return True

    if usuario_es_administrador(actor):
        return True

    if group and usuario_puede_gestionar_grupo(actor, group):
        return True

    return usuario_puede_asignar_trabajo(actor)


def _validate_assignment(*, actor, assigned_user, group=None):
    if not actor or not actor.is_authenticated:
        raise WorkspaceOperationError(
            "Se requiere un usuario autenticado para crear trabajo."
        )

    if group and not usuario_es_miembro_activo(actor, group):
        raise WorkspaceOperationError(
            "No perteneces a este grupo de trabajo."
        )

    if not user_can_assign_to_other_user(
        actor,
        assigned_user,
        group,
    ):
        raise WorkspaceOperationError(
            "No tienes permiso para asignar trabajo a otro usuario."
        )


@transaction.atomic
def create_workspace_task(
    *,
    actor,
    title,
    assigned_to=None,
    description="",
    task_type="general",
    priority="medium",
    group=None,
    start_at=None,
    due_at=None,
    reminder_at=None,
    is_important=False,
    is_private=False,
    related_contact_request=None,
):
    assigned_user = assigned_to or actor

    _validate_assignment(
        actor=actor,
        assigned_user=assigned_user,
        group=group,
    )

    cleaned_title = title.strip()

    if not cleaned_title:
        raise WorkspaceOperationError(
            "La tarea debe tener un título."
        )

    if start_at and due_at and due_at < start_at:
        raise WorkspaceOperationError(
            "La fecha límite no puede ser anterior al inicio."
        )

    task = Task(
        title=cleaned_title,
        description=description.strip(),
        task_type=task_type,
        priority=priority,
        group=group,
        created_by=actor,
        assigned_to=assigned_user,
        start_at=start_at,
        due_at=due_at,
        reminder_at=reminder_at,
        is_important=is_important,
        is_private=is_private,
        related_contact_request=related_contact_request,
    )
    task.full_clean()
    task.save()

    notify_task_assigned(
        task,
        actor=actor,
    )

    return task


@transaction.atomic
def create_workspace_event(
    *,
    actor,
    title,
    start_at,
    assigned_to=None,
    participants=None,
    description="",
    event_type="meeting",
    group=None,
    end_at=None,
    is_all_day=False,
    location="",
    related_task=None,
    related_contact_request=None,
):
    assigned_user = assigned_to or actor

    _validate_assignment(
        actor=actor,
        assigned_user=assigned_user,
        group=group,
    )

    cleaned_title = title.strip()

    if not cleaned_title:
        raise WorkspaceOperationError(
            "El evento debe tener un título."
        )

    if not start_at:
        raise WorkspaceOperationError(
            "El evento debe tener fecha y hora de inicio."
        )

    if end_at and end_at < start_at:
        raise WorkspaceOperationError(
            "La fecha de fin no puede ser anterior al inicio."
        )

    event = CalendarEvent(
        title=cleaned_title,
        description=description.strip(),
        event_type=event_type,
        group=group,
        created_by=actor,
        assigned_to=assigned_user,
        start_at=start_at,
        end_at=end_at,
        is_all_day=is_all_day,
        location=location.strip(),
        related_task=related_task,
        related_contact_request=related_contact_request,
    )
    event.full_clean()
    event.save()

    participant_list = list(participants or [])

    if participant_list:
        event.participants.set(participant_list)

    notify_event_assigned(
        event,
        actor=actor,
    )

    return event


@transaction.atomic
def create_workspace_reminder(
    *,
    actor,
    title,
    remind_at,
    user=None,
    message="",
    group=None,
    task=None,
    event=None,
):
    if task and event:
        raise WorkspaceOperationError(
            "El recordatorio debe vincularse a una tarea o "
            "a un evento, no a ambos."
        )

    resolved_group = group

    if not resolved_group and task and task.group:
        resolved_group = task.group

    if not resolved_group and event and event.group:
        resolved_group = event.group

    assigned_user = user or actor

    _validate_assignment(
        actor=actor,
        assigned_user=assigned_user,
        group=resolved_group,
    )

    cleaned_title = title.strip()

    if not cleaned_title:
        raise WorkspaceOperationError(
            "El recordatorio debe tener un título."
        )

    if not remind_at:
        raise WorkspaceOperationError(
            "El recordatorio debe tener fecha y hora."
        )

    reminder = Reminder(
        created_by=actor,
        user=assigned_user,
        group=resolved_group,
        task=task,
        event=event,
        title=cleaned_title,
        message=message.strip(),
        remind_at=remind_at,
    )
    reminder.full_clean()
    reminder.save()

    notify_reminder_assigned(
        reminder,
        actor=actor,
    )

    return reminder
