from django.core.exceptions import ValidationError
from django.db import transaction

from crm.models import CRMWorkItemLink, Opportunity, School


class CRMWorkItemLinkError(ValidationError):
    pass


def _selected_item(*, task, event, reminder):
    selected = [
        ("task", task),
        ("event", event),
        ("reminder", reminder),
    ]
    selected = [
        (item_type, item)
        for item_type, item in selected
        if item is not None
    ]

    if len(selected) != 1:
        raise CRMWorkItemLinkError(
            "Debe indicar exactamente una tarea, un evento "
            "o un recordatorio."
        )

    return selected[0]


@transaction.atomic
def link_crm_work_item(
    *,
    school,
    created_by,
    task=None,
    event=None,
    reminder=None,
    opportunity=None,
    contact=None,
    origin_activity=None,
):
    locked_school = (
        School.objects
        .select_for_update()
        .get(pk=school.pk)
    )

    locked_opportunity = None

    if opportunity is not None:
        locked_opportunity = (
            Opportunity.objects
            .select_for_update()
            .select_related("school", "stage")
            .get(pk=opportunity.pk)
        )

        if locked_opportunity.school_id != locked_school.id:
            raise CRMWorkItemLinkError(
                "La oportunidad no pertenece al colegio indicado."
            )

        if locked_opportunity.is_closed:
            raise CRMWorkItemLinkError(
                "No se puede agregar trabajo pendiente a una "
                "oportunidad cerrada."
            )

    if (
        contact is not None
        and contact.school_id != locked_school.id
    ):
        raise CRMWorkItemLinkError(
            "El contacto no pertenece al colegio."
        )

    if (
        origin_activity is not None
        and origin_activity.school_id != locked_school.id
    ):
        raise CRMWorkItemLinkError(
            "La actividad de origen no pertenece al colegio."
        )

    if (
        origin_activity is not None
        and locked_opportunity is not None
        and origin_activity.opportunity_id
        and origin_activity.opportunity_id != locked_opportunity.id
    ):
        raise CRMWorkItemLinkError(
            "La actividad de origen pertenece a otra oportunidad."
        )

    item_type, item = _selected_item(
        task=task,
        event=event,
        reminder=reminder,
    )

    filter_kwargs = {item_type: item}
    existing = (
        CRMWorkItemLink.objects
        .filter(**filter_kwargs)
        .select_related("school", "opportunity", "contact")
        .first()
    )

    if existing:
        same_context = (
            existing.school_id == locked_school.id
            and existing.opportunity_id
            == (
                locked_opportunity.id
                if locked_opportunity is not None
                else None
            )
            and existing.contact_id
            == (contact.id if contact is not None else None)
        )

        if same_context:
            return existing

        raise CRMWorkItemLinkError(
            "Este elemento de trabajo ya está vinculado "
            "a otro contexto comercial."
        )

    link = CRMWorkItemLink(
        school=locked_school,
        contact=contact,
        opportunity=locked_opportunity,
        origin_activity=origin_activity,
        task=task,
        event=event,
        reminder=reminder,
        created_by=created_by,
    )
    link.full_clean()
    link.save()

    return link


def link_work_item_to_school(
    *,
    school,
    created_by,
    task=None,
    event=None,
    reminder=None,
    contact=None,
    origin_activity=None,
):
    return link_crm_work_item(
        school=school,
        created_by=created_by,
        task=task,
        event=event,
        reminder=reminder,
        contact=contact,
        origin_activity=origin_activity,
    )


def link_work_item_to_opportunity(
    *,
    opportunity,
    created_by,
    task=None,
    event=None,
    reminder=None,
    origin_activity=None,
):
    contact = (
        origin_activity.contact
        if origin_activity is not None
        and origin_activity.contact_id
        else None
    )

    return link_crm_work_item(
        school=opportunity.school,
        opportunity=opportunity,
        contact=contact,
        created_by=created_by,
        task=task,
        event=event,
        reminder=reminder,
        origin_activity=origin_activity,
    )
