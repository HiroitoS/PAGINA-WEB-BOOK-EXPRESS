"""Consultas de visibilidad de ToDo y calendario, sin transporte HTTP.

Las reglas de acceso a tareas y recordatorios se concentran aquí para que
las vistas API y otros servicios consulten una única fuente de permisos.
"""

from django.db.models import Q

from accounts.permissions import usuario_es_administrador

from .models import (
    CalendarEvent,
    Reminder,
    Task,
    WorkspaceGroup,
    WorkspaceMembership,
    WorkspaceTaskList,
)


def get_user_group_ids(user):
    return WorkspaceMembership.objects.filter(
        user=user,
        is_active=True,
        group__is_active=True,
    ).values_list("group_id", flat=True)


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


def visible_task_lists_queryset(user):
    queryset = WorkspaceTaskList.objects.select_related(
        "workspace_group",
        "created_by",
    ).all()

    if usuario_es_administrador(user):
        return queryset

    group_ids = get_user_group_ids(user)

    return queryset.filter(
        Q(created_by=user)
        | Q(workspace_group_id__in=group_ids)
    ).distinct()


def visible_tasks_queryset(user):
    queryset = (
        Task.objects.select_related(
            "group",
            "task_list",
            "created_by",
            "assigned_to",
            "related_contact_request",
        )
        .all()
    )

    if usuario_es_administrador(user):
        return queryset

    group_ids = get_user_group_ids(user)

    # Una tarea privada no es visible por pertenecer al mismo equipo.
    # El creador y el responsable conservan el acceso; el administrador
    # dispone del acceso de supervisión definido arriba.
    return queryset.filter(
        Q(created_by=user)
        | Q(assigned_to=user)
        | Q(is_private=False, group_id__in=group_ids)
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

    managed_group_ids = WorkspaceMembership.objects.filter(
        user=user,
        is_active=True,
        role__in=["owner", "coordinator"],
        group__is_active=True,
    ).values_list("group_id", flat=True)

    return queryset.filter(
        Q(created_by=user)
        | Q(user=user)
        | Q(group__created_by=user)
        | Q(group_id__in=managed_group_ids)
        | Q(task__group_id__in=managed_group_ids)
        | Q(event__group_id__in=managed_group_ids)
    ).filter(
        Q(task__isnull=True)
        | Q(task__is_private=False)
        | Q(task__created_by=user)
        | Q(task__assigned_to=user)
    ).distinct()
