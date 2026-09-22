from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.permissions import usuario_es_administrador
from crm.models import (
    CRMWorkItemLink,
    CommercialTeamMembership,
    Opportunity,
    School,
)
from workspaces.services import (
    WorkspaceOperationError,
    create_workspace_event,
    create_workspace_reminder,
    create_workspace_task,
)

from .work_items import (
    link_crm_work_item,
    link_work_item_to_opportunity,
)


class CRMPlanningError(ValidationError):
    pass


def _locked_open_opportunity(opportunity):
    # Bloqueamos únicamente la fila de Opportunity.
    #
    # No usamos select_related() aquí porque team y owner son relaciones
    # opcionales. PostgreSQL implementa esas relaciones con OUTER JOIN y
    # no permite aplicar FOR UPDATE al lado nullable de ese JOIN.
    #
    # Las relaciones se cargan de forma diferida cuando sean necesarias.
    # Esto mantiene el bloqueo transaccional correcto sin bloquear tablas
    # compartidas ni generar errores específicos de PostgreSQL.
    locked = (
        Opportunity.objects
        .select_for_update()
        .get(pk=opportunity.pk)
    )

    if locked.is_closed:
        raise CRMPlanningError(
            "La oportunidad está cerrada. Debe reabrirse antes "
            "de programar nuevo trabajo."
        )

    return locked


def _resolve_assignee(*, opportunity, actor, assigned_to=None):
    return assigned_to or opportunity.owner or actor


def _validate_commercial_scope(*, opportunity, assigned_user):
    if not opportunity.team_id or not assigned_user:
        return

    if usuario_es_administrador(assigned_user):
        return

    belongs_to_team = CommercialTeamMembership.objects.filter(
        team_id=opportunity.team_id,
        user=assigned_user,
        is_active=True,
    ).exists()

    if not belongs_to_team:
        raise CRMPlanningError(
            "El responsable seleccionado no pertenece al equipo "
            "comercial de esta oportunidad."
        )


def _validate_related_item_belongs_to_opportunity(
    *,
    opportunity,
    task=None,
    event=None,
):
    if task and not CRMWorkItemLink.objects.filter(
        opportunity=opportunity,
        task=task,
    ).exists():
        raise CRMPlanningError(
            "La tarea seleccionada no pertenece a esta oportunidad."
        )

    if event and not CRMWorkItemLink.objects.filter(
        opportunity=opportunity,
        event=event,
    ).exists():
        raise CRMPlanningError(
            "El evento seleccionado no pertenece a esta oportunidad."
        )


@transaction.atomic
def create_opportunity_task(
    *,
    opportunity,
    actor,
    title,
    assigned_to=None,
    description="",
    priority="medium",
    group=None,
    start_at=None,
    due_at=None,
    reminder_at=None,
    is_important=False,
    is_private=False,
    origin_activity=None,
):
    locked = _locked_open_opportunity(opportunity)

    assignee = _resolve_assignee(
        opportunity=locked,
        actor=actor,
        assigned_to=assigned_to,
    )

    _validate_commercial_scope(
        opportunity=locked,
        assigned_user=assignee,
    )

    try:
        task = create_workspace_task(
            actor=actor,
            title=title,
            assigned_to=assignee,
            description=description,
            task_type="school",
            priority=priority,
            group=group,
            start_at=start_at,
            due_at=due_at,
            reminder_at=reminder_at,
            is_important=is_important,
            is_private=is_private,
        )
    except WorkspaceOperationError as exc:
        raise CRMPlanningError(exc.messages) from exc

    link_work_item_to_opportunity(
        opportunity=locked,
        created_by=actor,
        task=task,
        origin_activity=origin_activity,
    )

    return task


@transaction.atomic
def create_opportunity_event(
    *,
    opportunity,
    actor,
    title,
    start_at,
    assigned_to=None,
    participants=None,
    description="",
    event_type="visit",
    group=None,
    end_at=None,
    is_all_day=False,
    location="",
    related_task=None,
    origin_activity=None,
):
    locked = _locked_open_opportunity(opportunity)

    assignee = _resolve_assignee(
        opportunity=locked,
        actor=actor,
        assigned_to=assigned_to,
    )

    _validate_commercial_scope(
        opportunity=locked,
        assigned_user=assignee,
    )

    try:
        event = create_workspace_event(
            actor=actor,
            title=title,
            start_at=start_at,
            assigned_to=assignee,
            participants=participants,
            description=description,
            event_type=event_type,
            group=group,
            end_at=end_at,
            is_all_day=is_all_day,
            location=location,
            related_task=related_task,
        )
    except WorkspaceOperationError as exc:
        raise CRMPlanningError(exc.messages) from exc

    link_work_item_to_opportunity(
        opportunity=locked,
        created_by=actor,
        event=event,
        origin_activity=origin_activity,
    )

    return event


@transaction.atomic
def create_opportunity_reminder(
    *,
    opportunity,
    actor,
    title,
    remind_at,
    user=None,
    message="",
    group=None,
    task=None,
    event=None,
    origin_activity=None,
):
    locked = _locked_open_opportunity(opportunity)

    assignee = _resolve_assignee(
        opportunity=locked,
        actor=actor,
        assigned_to=user,
    )

    _validate_commercial_scope(
        opportunity=locked,
        assigned_user=assignee,
    )

    _validate_related_item_belongs_to_opportunity(
        opportunity=locked,
        task=task,
        event=event,
    )

    try:
        reminder = create_workspace_reminder(
            actor=actor,
            title=title,
            remind_at=remind_at,
            user=assignee,
            message=message,
            group=group,
            task=task,
            event=event,
        )
    except WorkspaceOperationError as exc:
        raise CRMPlanningError(exc.messages) from exc

    link_work_item_to_opportunity(
        opportunity=locked,
        created_by=actor,
        reminder=reminder,
        origin_activity=origin_activity,
    )

    return reminder



def _locked_school(school):
    return (
        School.objects
        .select_for_update()
        .get(pk=school.pk)
    )


def _resolve_school_assignee(*, school, actor, assigned_to=None):
    return assigned_to or school.owner or actor


def _validate_school_commercial_scope(*, school, assigned_user):
    if not school.team_id or not assigned_user:
        return

    if usuario_es_administrador(assigned_user):
        return

    belongs_to_team = CommercialTeamMembership.objects.filter(
        team_id=school.team_id,
        user=assigned_user,
        is_active=True,
    ).exists()

    if not belongs_to_team:
        raise CRMPlanningError(
            "El responsable seleccionado no pertenece al equipo "
            "comercial del colegio."
        )


@transaction.atomic
def create_school_task(
    *,
    school,
    actor,
    title,
    contact=None,
    opportunity=None,
    origin_activity=None,
    assigned_to=None,
    description="",
    priority="medium",
    group=None,
    start_at=None,
    due_at=None,
    reminder_at=None,
    is_important=False,
    is_private=False,
):
    locked_school = _locked_school(school)

    assignee = _resolve_school_assignee(
        school=locked_school,
        actor=actor,
        assigned_to=assigned_to,
    )

    _validate_school_commercial_scope(
        school=locked_school,
        assigned_user=assignee,
    )

    try:
        task = create_workspace_task(
            actor=actor,
            title=title,
            assigned_to=assignee,
            description=description,
            task_type="school",
            priority=priority,
            group=group,
            start_at=start_at,
            due_at=due_at,
            reminder_at=reminder_at,
            is_important=is_important,
            is_private=is_private,
        )
    except WorkspaceOperationError as exc:
        raise CRMPlanningError(exc.messages) from exc

    link_crm_work_item(
        school=locked_school,
        opportunity=opportunity,
        contact=contact,
        origin_activity=origin_activity,
        created_by=actor,
        task=task,
    )

    return task


@transaction.atomic
def create_school_event(
    *,
    school,
    actor,
    title,
    start_at,
    contact=None,
    opportunity=None,
    origin_activity=None,
    assigned_to=None,
    participants=None,
    description="",
    event_type="visit",
    group=None,
    end_at=None,
    is_all_day=False,
    location="",
    related_task=None,
):
    locked_school = _locked_school(school)

    assignee = _resolve_school_assignee(
        school=locked_school,
        actor=actor,
        assigned_to=assigned_to,
    )

    _validate_school_commercial_scope(
        school=locked_school,
        assigned_user=assignee,
    )

    try:
        event = create_workspace_event(
            actor=actor,
            title=title,
            start_at=start_at,
            assigned_to=assignee,
            participants=participants,
            description=description,
            event_type=event_type,
            group=group,
            end_at=end_at,
            is_all_day=is_all_day,
            location=location,
            related_task=related_task,
        )
    except WorkspaceOperationError as exc:
        raise CRMPlanningError(exc.messages) from exc

    link_crm_work_item(
        school=locked_school,
        opportunity=opportunity,
        contact=contact,
        origin_activity=origin_activity,
        created_by=actor,
        event=event,
    )

    return event


@transaction.atomic
def create_school_reminder(
    *,
    school,
    actor,
    title,
    remind_at,
    contact=None,
    opportunity=None,
    origin_activity=None,
    user=None,
    message="",
    group=None,
    task=None,
    event=None,
):
    locked_school = _locked_school(school)

    assignee = _resolve_school_assignee(
        school=locked_school,
        actor=actor,
        assigned_to=user,
    )

    _validate_school_commercial_scope(
        school=locked_school,
        assigned_user=assignee,
    )

    try:
        reminder = create_workspace_reminder(
            actor=actor,
            title=title,
            remind_at=remind_at,
            user=assignee,
            message=message,
            group=group,
            task=task,
            event=event,
        )
    except WorkspaceOperationError as exc:
        raise CRMPlanningError(exc.messages) from exc

    link_crm_work_item(
        school=locked_school,
        opportunity=opportunity,
        contact=contact,
        origin_activity=origin_activity,
        created_by=actor,
        reminder=reminder,
    )

    return reminder
