from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from crm.models import (
    CommercialTeamMembership,
    Opportunity,
    OpportunityStageHistory,
    PipelineStage,
)


class OpportunityTransitionError(ValidationError):
    pass


def _validate_stage_for_pipeline(*, pipeline, stage):
    if stage.pipeline_id != pipeline.id:
        raise OpportunityTransitionError(
            "La etapa no pertenece al pipeline seleccionado."
        )

    if not stage.is_active:
        raise OpportunityTransitionError(
            "No se puede utilizar una etapa inactiva."
        )


def _validate_contact_for_school(*, school, contact):
    if contact is None:
        return

    if contact.school_id != school.id:
        raise OpportunityTransitionError(
            "El contacto no pertenece al colegio seleccionado."
        )


def _validate_owner_for_team(*, owner, team):
    if owner is None or team is None:
        return

    belongs_to_team = CommercialTeamMembership.objects.filter(
        team=team,
        user=owner,
        is_active=True,
    ).exists()

    if not belongs_to_team:
        raise OpportunityTransitionError(
            "El asesor responsable no pertenece al equipo comercial "
            "seleccionado."
        )


@transaction.atomic
def create_opportunity(
    *,
    title,
    school,
    campaign,
    pipeline,
    created_by,
    stage=None,
    primary_contact=None,
    team=None,
    owner=None,
    notes="",
):
    if stage is None:
        try:
            stage = pipeline.stages.get(
                is_initial=True,
                is_active=True,
            )
        except PipelineStage.DoesNotExist as exc:
            raise OpportunityTransitionError(
                "El pipeline no tiene una etapa inicial activa."
            ) from exc
        except PipelineStage.MultipleObjectsReturned as exc:
            raise OpportunityTransitionError(
                "El pipeline tiene más de una etapa inicial activa."
            ) from exc

    _validate_stage_for_pipeline(
        pipeline=pipeline,
        stage=stage,
    )
    _validate_contact_for_school(
        school=school,
        contact=primary_contact,
    )

    resolved_team = team if team is not None else school.team
    resolved_owner = owner if owner is not None else school.owner

    _validate_owner_for_team(
        owner=resolved_owner,
        team=resolved_team,
    )

    opportunity = Opportunity(
        title=title,
        school=school,
        campaign=campaign,
        pipeline=pipeline,
        stage=stage,
        primary_contact=primary_contact,
        team=resolved_team,
        owner=resolved_owner,
        notes=notes,
        created_by=created_by,
    )
    opportunity.full_clean()
    opportunity.save()

    OpportunityStageHistory.objects.create(
        opportunity=opportunity,
        from_stage=None,
        to_stage=stage,
        changed_by=created_by,
        transition_type=OpportunityStageHistory.TransitionType.CREATED,
        note="Oportunidad creada.",
    )

    return opportunity


@transaction.atomic
def transition_opportunity_stage(
    *,
    opportunity,
    to_stage,
    changed_by,
    note="",
    allow_won=False,
):
    locked_opportunity = (
        Opportunity.objects
        .select_for_update()
        .select_related("pipeline", "stage")
        .get(pk=opportunity.pk)
    )

    current_stage = locked_opportunity.stage

    if current_stage.is_terminal:
        raise OpportunityTransitionError(
            "La oportunidad está cerrada. Use el flujo de reapertura."
        )

    _validate_stage_for_pipeline(
        pipeline=locked_opportunity.pipeline,
        stage=to_stage,
    )

    if current_stage.pk == to_stage.pk:
        raise OpportunityTransitionError(
            "La oportunidad ya se encuentra en esa etapa."
        )

    if (
        to_stage.category == PipelineStage.Category.WON
        and not allow_won
    ):
        raise OpportunityTransitionError(
            "La adopción confirmada debe cerrarse mediante "
            "el flujo de adopción."
        )

    cleaned_note = note.strip()

    if (
        to_stage.category == PipelineStage.Category.LOST
        and not cleaned_note
    ):
        raise OpportunityTransitionError(
            "Debe registrar el motivo de la oportunidad no concretada."
        )

    closed_at = None
    closed_by = None
    closure_note = ""

    if to_stage.category in {
        PipelineStage.Category.WON,
        PipelineStage.Category.LOST,
    }:
        closed_at = timezone.now()
        closed_by = changed_by
        closure_note = cleaned_note

    previous_stage = current_stage

    locked_opportunity.stage = to_stage
    locked_opportunity.closed_at = closed_at
    locked_opportunity.closed_by = closed_by
    locked_opportunity.closure_note = closure_note
    locked_opportunity.save(
        update_fields=[
            "stage",
            "closed_at",
            "closed_by",
            "closure_note",
            "updated_at",
        ]
    )

    OpportunityStageHistory.objects.create(
        opportunity=locked_opportunity,
        from_stage=previous_stage,
        to_stage=to_stage,
        changed_by=changed_by,
        transition_type=(
            OpportunityStageHistory.TransitionType.STAGE_CHANGE
        ),
        note=cleaned_note,
    )

    return locked_opportunity


@transaction.atomic
def reopen_opportunity(
    *,
    opportunity,
    to_stage,
    changed_by,
    reason,
):
    locked_opportunity = (
        Opportunity.objects
        .select_for_update()
        .select_related("pipeline", "stage")
        .get(pk=opportunity.pk)
    )

    if not locked_opportunity.stage.is_terminal:
        raise OpportunityTransitionError(
            "Solo se puede reabrir una oportunidad cerrada."
        )

    _validate_stage_for_pipeline(
        pipeline=locked_opportunity.pipeline,
        stage=to_stage,
    )

    if to_stage.category != PipelineStage.Category.OPEN:
        raise OpportunityTransitionError(
            "La reapertura debe volver a una etapa abierta."
        )

    cleaned_reason = reason.strip()

    if not cleaned_reason:
        raise OpportunityTransitionError(
            "Debe registrar el motivo de reapertura."
        )

    previous_stage = locked_opportunity.stage

    locked_opportunity.stage = to_stage
    locked_opportunity.closed_at = None
    locked_opportunity.closed_by = None
    locked_opportunity.closure_note = ""
    locked_opportunity.save(
        update_fields=[
            "stage",
            "closed_at",
            "closed_by",
            "closure_note",
            "updated_at",
        ]
    )

    OpportunityStageHistory.objects.create(
        opportunity=locked_opportunity,
        from_stage=previous_stage,
        to_stage=to_stage,
        changed_by=changed_by,
        transition_type=(
            OpportunityStageHistory.TransitionType.REOPENED
        ),
        note=cleaned_reason,
    )

    return locked_opportunity
