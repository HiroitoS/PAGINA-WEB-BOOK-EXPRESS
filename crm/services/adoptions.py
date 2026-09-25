from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from crm.models import (
    Adoption,
    AdoptionItem,
    CommercialQuotation,
    Opportunity,
    PipelineStage,
)

from .opportunities import transition_opportunity_stage


class AdoptionError(ValidationError):
    pass


def _user_display_name(user):
    if user is None:
        return ""

    full_name = user.get_full_name().strip()

    return full_name or user.get_username()


@transaction.atomic
def confirm_adoption(
    *,
    quotation,
    authorized_contact,
    signed_at,
    actor,
    notes="",
    reading_month_by_item=None,
):
    locked_quotation = (
        CommercialQuotation.objects
        .select_for_update()
        .get(pk=quotation.pk)
    )

    opportunity = (
        Opportunity.objects
        .select_for_update()
        .select_related(
            "school",
            "campaign",
            "pipeline",
            "stage",
        )
        .get(pk=locked_quotation.opportunity_id)
    )

    if locked_quotation.status != CommercialQuotation.Status.ACCEPTED:
        raise AdoptionError(
            "La adopción requiere una cotización aceptada."
        )

    if opportunity.is_closed:
        raise AdoptionError(
            "La oportunidad ya se encuentra cerrada."
        )

    if opportunity.stage.code != "cotizacion_enviada":
        raise AdoptionError(
            "La oportunidad debe estar en Cotización enviada "
            "antes de confirmar la adopción."
        )

    if authorized_contact is None:
        raise AdoptionError(
            "Debe indicar el directivo que autorizó la adopción."
        )

    if authorized_contact.school_id != opportunity.school_id:
        raise AdoptionError(
            "El directivo seleccionado no pertenece al colegio."
        )

    if not authorized_contact.is_active:
        raise AdoptionError(
            "El directivo seleccionado está inactivo."
        )

    if signed_at is None:
        raise AdoptionError(
            "Debe registrar la fecha de firma o aprobación."
        )

    if signed_at > timezone.now():
        raise AdoptionError(
            "La fecha de firma o aprobación no puede estar en el futuro."
        )

    if Adoption.objects.filter(
        opportunity=opportunity,
        is_current=True,
    ).exists():
        raise AdoptionError(
            "La oportunidad ya tiene una adopción vigente."
        )

    quotation_items = list(
        locked_quotation.items
        .select_related("product")
        .order_by("id")
    )

    if not quotation_items:
        raise AdoptionError(
            "La cotización aceptada no contiene productos."
        )

    won_stages = list(
        PipelineStage.objects.filter(
            pipeline=opportunity.pipeline,
            category=PipelineStage.Category.WON,
            is_active=True,
        ).order_by("order", "id")[:2]
    )

    if len(won_stages) != 1:
        raise AdoptionError(
            "El pipeline debe tener exactamente una etapa de cierre ganado."
        )

    current_version = (
        Adoption.objects
        .filter(opportunity=opportunity)
        .aggregate(max_version=Max("version"))
        .get("max_version")
        or 0
    )

    confirmed_at = timezone.now()

    adoption = Adoption(
        opportunity=opportunity,
        quotation=locked_quotation,
        school=opportunity.school,
        campaign=opportunity.campaign,
        version=current_version + 1,
        is_current=True,
        school_name_snapshot=opportunity.school.name,
        campaign_name_snapshot=opportunity.campaign.name,
        advisor=opportunity.owner,
        advisor_name_snapshot=_user_display_name(opportunity.owner),
        authorized_contact=authorized_contact,
        authorized_contact_name_snapshot=authorized_contact.full_name,
        signed_at=signed_at,
        confirmed_at=confirmed_at,
        confirmed_by=actor,
        notes=(notes or "").strip(),
    )
    adoption.full_clean()
    adoption.save()

    reading_month_by_item = reading_month_by_item or {}

    for quotation_item in quotation_items:
        adoption_item = AdoptionItem(
            adoption=adoption,
            quotation_item=quotation_item,
            product=quotation_item.product,
            product_name_snapshot=(
                quotation_item.product_name_snapshot
            ),
            provider_name_snapshot=(
                quotation_item.provider_name_snapshot
            ),
            level_name_snapshot=(
                quotation_item.level_name_snapshot
            ),
            grade_name_snapshot=(
                quotation_item.grade_name_snapshot
            ),
            area_name_snapshot=(
                quotation_item.area_name_snapshot
            ),
            quantity=quotation_item.quantity,
            pvp=quotation_item.pvp,
            supplier_cost=quotation_item.supplier_cost,
            school_price=quotation_item.school_price,
            parent_price=quotation_item.parent_price,
            school_commission=quotation_item.school_commission,
            reading_month=reading_month_by_item.get(
                quotation_item.id
            ),
        )
        adoption_item.full_clean()
        adoption_item.save()

    transition_opportunity_stage(
        opportunity=opportunity,
        to_stage=won_stages[0],
        changed_by=actor,
        note=(
            f"Adopción confirmada con cotización "
            f"v{locked_quotation.version}. "
            f"Directivo: {authorized_contact.full_name}."
        ),
        allow_won=True,
    )

    return adoption
