from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from crm.models import CommercialActivity, Opportunity, School


class CommercialActivityError(ValidationError):
    pass


@transaction.atomic
def record_commercial_activity(
    *,
    activity_type,
    summary,
    result,
    performed_by,
    created_by,
    school=None,
    opportunity=None,
    contact=None,
    occurred_at=None,
    is_important=False,
):
    locked_opportunity = None

    if opportunity is not None:
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

        resolved_school = locked_opportunity.school

        if school is not None and school.pk != resolved_school.pk:
            raise CommercialActivityError(
                "La oportunidad no pertenece al colegio indicado."
            )
    elif school is not None:
        resolved_school = (
            School.objects
            .select_for_update()
            .get(pk=school.pk)
        )
    else:
        raise CommercialActivityError(
            "Debe indicar el colegio de la actividad."
        )

    if (
        contact is not None
        and contact.school_id != resolved_school.id
    ):
        raise CommercialActivityError(
            "El contacto no pertenece al colegio."
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
        school=resolved_school,
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

    if locked_opportunity and (
        locked_opportunity.last_activity_at is None
        or activity_date > locked_opportunity.last_activity_at
    ):
        locked_opportunity.last_activity_at = activity_date
        locked_opportunity.save(
            update_fields=["last_activity_at", "updated_at"]
        )

    return activity
