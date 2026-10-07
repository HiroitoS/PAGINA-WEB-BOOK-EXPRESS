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

from .history import record_history_event
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

    advisor = opportunity.owner
    advisor_profile = (
        getattr(advisor, "book_express_profile", None)
        if advisor is not None
        else None
    )
    advisor_name = (
        locked_quotation.advisor_name_snapshot
        or _user_display_name(advisor)
    )
    advisor_phone = (
        locked_quotation.advisor_phone_snapshot
        or (
            getattr(advisor_profile, "phone", "")
            if advisor_profile is not None
            else ""
        )
    )
    advisor_whatsapp = (
        locked_quotation.advisor_whatsapp_snapshot
        or (
            getattr(advisor_profile, "whatsapp", "")
            if advisor_profile is not None
            else ""
        )
    )
    authorized_phone = (
        authorized_contact.whatsapp
        or authorized_contact.phone
        or ""
    )

    adoption = Adoption(
        opportunity=opportunity,
        quotation=locked_quotation,
        school=opportunity.school,
        campaign=opportunity.campaign,
        version=current_version + 1,
        is_current=True,
        school_name_snapshot=opportunity.school.name,
        campaign_name_snapshot=opportunity.campaign.name,
        advisor=advisor,
        advisor_name_snapshot=advisor_name,
        advisor_phone_snapshot=advisor_phone,
        advisor_whatsapp_snapshot=advisor_whatsapp,
        authorized_contact=authorized_contact,
        authorized_contact_name_snapshot=authorized_contact.full_name,
        authorized_contact_position_snapshot=(
            authorized_contact.position or ""
        ),
        authorized_contact_phone_snapshot=authorized_phone,
        authorized_contact_email_snapshot=authorized_contact.email or "",
        sale_mode=locked_quotation.sale_mode,
        service_date=locked_quotation.service_date,
        service_end_date=locked_quotation.service_end_date,
        fair_start_time=locked_quotation.fair_start_time,
        fair_end_time=locked_quotation.fair_end_time,
        signed_at=signed_at,
        confirmed_at=confirmed_at,
        confirmed_by=actor,
        notes=(notes or "").strip(),
    )
    adoption.full_clean()
    adoption.save()

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
            supplier_discount_percent=(
                quotation_item.supplier_discount_percent
            ),
            school_price=quotation_item.school_price,
            parent_price=quotation_item.parent_price,
            school_commission=quotation_item.school_commission,
            reading_month=quotation_item.reading_month,
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

    record_history_event(
        school=opportunity.school,
        opportunity=opportunity,
        contact=authorized_contact,
        actor=actor,
        category="adoption",
        event_type="adoption_confirmed",
        title=f"Adopción v{adoption.version} confirmada",
        description=(
            f"Directivo: "
            f"{adoption.authorized_contact_name_snapshot}."
        ),
        source_type="adoption",
        source_id=adoption.id,
        metadata={
            "version": adoption.version,
            "quotation_id": adoption.quotation_id,
        },
        occurred_at=adoption.confirmed_at or adoption.created_at,
    )

    return adoption
