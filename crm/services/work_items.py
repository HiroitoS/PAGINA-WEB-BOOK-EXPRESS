from django.core.exceptions import ValidationError
from django.db import transaction

from crm.models import CRMWorkItemLink, Opportunity


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
def link_work_item_to_opportunity(
    *,
    opportunity,
    created_by,
    task=None,
    event=None,
    reminder=None,
    origin_activity=None,
):
    locked_opportunity = (
        Opportunity.objects
        .select_for_update()
        .select_related("stage")
        .get(pk=opportunity.pk)
    )

    if locked_opportunity.is_closed:
        raise CRMWorkItemLinkError(
            "No se puede agregar trabajo pendiente a una "
            "oportunidad cerrada."
        )

    item_type, item = _selected_item(
        task=task,
        event=event,
        reminder=reminder,
    )

    if (
        origin_activity is not None
        and origin_activity.opportunity_id != locked_opportunity.id
    ):
        raise CRMWorkItemLinkError(
            "La actividad de origen no pertenece a esta oportunidad."
        )

    filter_kwargs = {item_type: item}
    existing = (
        CRMWorkItemLink.objects
        .filter(**filter_kwargs)
        .select_related("opportunity")
        .first()
    )

    if existing:
        if existing.opportunity_id == locked_opportunity.id:
            return existing

        raise CRMWorkItemLinkError(
            "Este elemento de trabajo ya está vinculado "
            "a otra oportunidad."
        )

    link = CRMWorkItemLink(
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
