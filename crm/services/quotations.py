from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from crm.models import (
    CommercialQuotation,
    CommercialQuotationItem,
    Opportunity,
    PipelineStage,
)

from .opportunities import transition_opportunity_stage


class CommercialQuotationError(ValidationError):
    pass


def _decimal_value(value, *, field_label):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CommercialQuotationError(
            f"{field_label} debe ser un importe válido."
        ) from exc


def _product_snapshot(product):
    return {
        "product_name_snapshot": product.name,
        "provider_name_snapshot": product.provider.name,
        "level_name_snapshot": (
            product.level.name if product.level_id else ""
        ),
        "grade_name_snapshot": (
            product.grade.name if product.grade_id else ""
        ),
        "area_name_snapshot": (
            product.area.name if product.area_id else ""
        ),
    }


@transaction.atomic
def create_commercial_quotation(
    *,
    opportunity,
    actor,
    items,
    notes="",
):
    locked_opportunity = (
        Opportunity.objects
        .select_for_update()
        .select_related("school", "campaign", "stage")
        .get(pk=opportunity.pk)
    )

    if locked_opportunity.is_closed:
        raise CommercialQuotationError(
            "No se puede cotizar una oportunidad cerrada."
        )

    if not items:
        raise CommercialQuotationError(
            "La cotización debe incluir al menos un producto."
        )

    if locked_opportunity.quotations.filter(
        status=CommercialQuotation.Status.ACCEPTED,
    ).exists():
        raise CommercialQuotationError(
            "La oportunidad ya tiene una cotización aceptada."
        )

    current_version = (
        locked_opportunity.quotations
        .aggregate(max_version=Max("version"))
        .get("max_version")
        or 0
    )

    quotation = CommercialQuotation(
        opportunity=locked_opportunity,
        version=current_version + 1,
        status=CommercialQuotation.Status.DRAFT,
        school_name_snapshot=locked_opportunity.school.name,
        campaign_name_snapshot=locked_opportunity.campaign.name,
        notes=(notes or "").strip(),
        created_by=actor,
    )
    quotation.full_clean()
    quotation.save()

    for payload in items:
        product = payload.get("product")

        if product is None:
            raise CommercialQuotationError(
                "Cada ítem debe indicar un producto."
            )

        if not product.is_active:
            raise CommercialQuotationError(
                f"El producto {product.name} está inactivo."
            )

        try:
            quantity = int(payload.get("quantity"))
        except (TypeError, ValueError) as exc:
            raise CommercialQuotationError(
                "La cantidad debe ser un número entero."
            ) from exc

        item = CommercialQuotationItem(
            quotation=quotation,
            product=product,
            quantity=quantity,
            pvp=_decimal_value(
                payload.get("pvp"),
                field_label="PVP",
            ),
            supplier_cost=_decimal_value(
                payload.get("supplier_cost"),
                field_label="Costo editorial",
            ),
            school_price=_decimal_value(
                payload.get("school_price"),
                field_label="Precio colegio",
            ),
            parent_price=_decimal_value(
                payload.get("parent_price"),
                field_label="Precio PPFF",
            ),
            school_commission=_decimal_value(
                payload.get("school_commission", "0.00"),
                field_label="Comisión colegio",
            ),
            **_product_snapshot(product),
        )
        item.full_clean()
        item.save()

    return quotation


@transaction.atomic
def send_commercial_quotation(*, quotation, actor):
    locked_quotation = (
        CommercialQuotation.objects
        .select_for_update()
        .select_related(
            "opportunity__pipeline",
            "opportunity__stage",
        )
        .get(pk=quotation.pk)
    )

    if locked_quotation.status != CommercialQuotation.Status.DRAFT:
        raise CommercialQuotationError(
            "Solo una cotización en borrador puede enviarse."
        )

    if not locked_quotation.items.exists():
        raise CommercialQuotationError(
            "No se puede enviar una cotización sin productos."
        )

    if locked_quotation.opportunity.quotations.exclude(
        pk=locked_quotation.pk,
    ).filter(
        status=CommercialQuotation.Status.ACCEPTED,
    ).exists():
        raise CommercialQuotationError(
            "Existe otra cotización aceptada para esta oportunidad."
        )

    quotation_stage = (
        PipelineStage.objects
        .filter(
            pipeline=locked_quotation.opportunity.pipeline,
            code="cotizacion_enviada",
            category=PipelineStage.Category.OPEN,
            is_active=True,
        )
        .first()
    )

    if quotation_stage is None:
        raise CommercialQuotationError(
            "El pipeline no tiene configurada la etapa de cotización enviada."
        )

    locked_quotation.opportunity.quotations.exclude(
        pk=locked_quotation.pk,
    ).filter(
        status__in=[
            CommercialQuotation.Status.DRAFT,
            CommercialQuotation.Status.SENT,
        ],
    ).update(
        status=CommercialQuotation.Status.SUPERSEDED,
        updated_at=timezone.now(),
    )

    locked_quotation.status = CommercialQuotation.Status.SENT
    locked_quotation.sent_at = timezone.now()
    locked_quotation.sent_by = actor
    locked_quotation.save(
        update_fields=[
            "status",
            "sent_at",
            "sent_by",
            "updated_at",
        ]
    )

    if locked_quotation.opportunity.stage_id != quotation_stage.id:
        transition_opportunity_stage(
            opportunity=locked_quotation.opportunity,
            to_stage=quotation_stage,
            changed_by=actor,
            note=(
                f"Cotización v{locked_quotation.version} enviada."
            ),
        )

    return locked_quotation


@transaction.atomic
def accept_commercial_quotation(*, quotation, actor):
    locked_quotation = (
        CommercialQuotation.objects
        .select_for_update()
        .select_related("opportunity")
        .get(pk=quotation.pk)
    )

    if locked_quotation.status != CommercialQuotation.Status.SENT:
        raise CommercialQuotationError(
            "Solo una cotización enviada puede marcarse como aceptada."
        )

    if locked_quotation.opportunity.quotations.exclude(
        pk=locked_quotation.pk,
    ).filter(
        status=CommercialQuotation.Status.ACCEPTED,
    ).exists():
        raise CommercialQuotationError(
            "La oportunidad ya tiene otra cotización aceptada."
        )

    locked_quotation.opportunity.quotations.exclude(
        pk=locked_quotation.pk,
    ).filter(
        status__in=[
            CommercialQuotation.Status.DRAFT,
            CommercialQuotation.Status.SENT,
        ],
    ).update(
        status=CommercialQuotation.Status.SUPERSEDED,
        updated_at=timezone.now(),
    )

    locked_quotation.status = CommercialQuotation.Status.ACCEPTED
    locked_quotation.accepted_at = timezone.now()
    locked_quotation.accepted_by = actor
    locked_quotation.save(
        update_fields=[
            "status",
            "accepted_at",
            "accepted_by",
            "updated_at",
        ]
    )

    return locked_quotation
