from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from crm.models import CommercialActivity, Opportunity


class CommercialActivityError(ValidationError):
    pass


@transaction.atomic
def record_commercial_activity(
    *,
    opportunity,
    activity_type,
    summary,
    result,
    performed_by,
    created_by,
    contact=None,
    occurred_at=None,
    is_important=False,
):
    locked_opportunity = (
        Opportunity.objects
        .select_for_update()
        .select_related("school", "stage")
        .get(pk=opportunity.pk)
    )

    if locked_opportunity.is_closed:
        raise CommercialActivityError(
            "La oportunidad está cerrada. Debe reabrirse antes de "
            "registrar nueva actividad comercial."
        )

    if (
        contact is not None
        and contact.school_id != locked_opportunity.school_id
    ):
        raise CommercialActivityError(
            "El contacto no pertenece al colegio de la oportunidad."
        )

    cleaned_summary = summary.strip()
    cleaned_result = result.strip()

    if not cleaned_summary:
        raise CommercialActivityError(
            "Debe registrar un resumen de la actividad."
        )

    if not cleaned_result:
        raise CommercialActivityError(
            "Debe registrar el resultado de la actividad."
        )

    activity_date = occurred_at or timezone.now()

    activity = CommercialActivity(
        opportunity=locked_opportunity,
        contact=contact,
        performed_by=performed_by,
        activity_type=activity_type,
        summary=cleaned_summary,
        result=cleaned_result,
        occurred_at=activity_date,
        is_important=is_important,
        created_by=created_by,
    )
    activity.full_clean()
    activity.save()

    if (
        locked_opportunity.last_activity_at is None
        or activity_date > locked_opportunity.last_activity_at
    ):
        locked_opportunity.last_activity_at = activity_date
        locked_opportunity.save(
            update_fields=["last_activity_at", "updated_at"]
        )

    return activity
