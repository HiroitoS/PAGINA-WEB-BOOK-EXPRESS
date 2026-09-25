from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from catalog.models import ProductPrice
from crm.models import (
    CommercialProjection,
    CommercialProjectionGrade,
    CommercialProjectionItem,
    Opportunity,
)


class CommercialProjectionError(ValidationError):
    pass


def _positive_int(value, *, field_label, allow_none=False):
    if value is None and allow_none:
        return None

    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise CommercialProjectionError(
            f"{field_label} debe ser un número entero."
        ) from exc

    if parsed < 1:
        raise CommercialProjectionError(
            f"{field_label} debe ser mayor a cero."
        )

    return parsed


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


def _resolve_population_values(
    *,
    service,
    grade,
    section_count,
    student_count,
):
    resolved_section_count = (
        _positive_int(
            section_count,
            field_label="Número de secciones",
            allow_none=True,
        )
        if section_count is not None
        else None
    )
    resolved_student_count = (
        _positive_int(
            student_count,
            field_label="Alumnos proyectados",
            allow_none=True,
        )
        if student_count is not None
        else None
    )

    if resolved_section_count is not None and resolved_student_count is not None:
        return resolved_section_count, resolved_student_count

    population = (
        service.population_records
        .filter(is_current=True)
        .prefetch_related("details")
        .first()
    )

    population_detail = None

    if population is not None:
        population_detail = next(
            (
                detail
                for detail in population.details.all()
                if detail.grade_id == grade.id
            ),
            None,
        )

    if resolved_section_count is None and population_detail is not None:
        resolved_section_count = population_detail.section_count

    if resolved_student_count is None and population_detail is not None:
        resolved_student_count = population_detail.student_count

    if resolved_student_count is None:
        raise CommercialProjectionError(
            (
                f"No existe población por grado para "
                f"{service.level.name} - {grade.name}. "
                "Registra la población del colegio o indica "
                "los alumnos proyectados."
            )
        )

    return resolved_section_count, resolved_student_count


def resolve_projection_price(*, product, campaign):
    prices = ProductPrice.objects.filter(
        product=product,
        year=campaign.year,
        is_active=True,
    )

    campaign_label = campaign.get_campaign_type_display()

    price = (
        prices
        .filter(campaign__iexact=campaign_label)
        .order_by("-updated_at", "-id")
        .first()
    )

    if price is None:
        candidates = list(
            prices.order_by("-updated_at", "-id")[:2]
        )

        if len(candidates) == 1:
            price = candidates[0]
        elif not candidates:
            raise CommercialProjectionError(
                (
                    f"{product.name} no tiene precio activo para "
                    f"{campaign.year}."
                )
            )
        else:
            raise CommercialProjectionError(
                (
                    f"{product.name} tiene más de un precio activo "
                    f"para {campaign.year} y ninguno corresponde a "
                    f"{campaign_label}."
                )
            )

    if price.price is None:
        raise CommercialProjectionError(
            (
                f"{product.name} no tiene un precio numérico "
                f"registrado para {campaign.year}."
            )
        )

    return price


@transaction.atomic
def create_commercial_projection_revision(
    *,
    opportunity,
    actor,
    grade_lines,
    items,
    notes="",
):
    locked_opportunity = (
        Opportunity.objects
        .select_for_update()
        .select_related(
            "school",
            "campaign",
            "stage",
        )
        .get(pk=opportunity.pk)
    )

    if locked_opportunity.is_closed:
        raise CommercialProjectionError(
            "No se puede proyectar una oportunidad cerrada."
        )

    if not grade_lines:
        raise CommercialProjectionError(
            "La proyección debe incluir al menos un grado."
        )

    prepared_grades = {}
    prepared_items = []

    for payload in grade_lines:
        service = payload.get("service")
        grade = payload.get("grade")

        if service is None or grade is None:
            raise CommercialProjectionError(
                "Cada grado debe indicar nivel educativo y grado."
            )

        if service.school_id != locked_opportunity.school_id:
            raise CommercialProjectionError(
                (
                    f"El nivel {service.level.name} no pertenece "
                    "al colegio de esta oportunidad."
                )
            )

        if not service.is_active:
            raise CommercialProjectionError(
                (
                    f"El nivel {service.level.name} está inactivo "
                    "en este colegio."
                )
            )

        if not grade.is_active:
            raise CommercialProjectionError(
                f"El grado {grade.name} está inactivo."
            )

        key = (service.id, grade.id)

        if key in prepared_grades:
            raise CommercialProjectionError(
                (
                    f"{service.level.name} - {grade.name} "
                    "está repetido en la proyección."
                )
            )

        section_count, student_count = _resolve_population_values(
            service=service,
            grade=grade,
            section_count=payload.get("section_count"),
            student_count=payload.get("student_count"),
        )

        prepared_grades[key] = {
            "service": service,
            "grade": grade,
            "section_count": section_count,
            "student_count": student_count,
        }

    seen_items = set()

    for payload in items or []:
        service = payload.get("service")
        grade = payload.get("grade")
        product = payload.get("product")

        if service is None or grade is None or product is None:
            raise CommercialProjectionError(
                (
                    "Cada producto debe indicar nivel educativo, "
                    "grado y producto."
                )
            )

        grade_key = (service.id, grade.id)

        if grade_key not in prepared_grades:
            raise CommercialProjectionError(
                (
                    f"{product.name} referencia un grado que no "
                    "forma parte de esta proyección."
                )
            )

        if not product.is_active:
            raise CommercialProjectionError(
                f"El producto {product.name} está inactivo."
            )

        if product.level_id and product.level_id != service.level_id:
            raise CommercialProjectionError(
                (
                    f"{product.name} no corresponde al nivel "
                    f"{service.level.name}."
                )
            )

        if product.grade_id and product.grade_id != grade.id:
            raise CommercialProjectionError(
                (
                    f"{product.name} no corresponde al grado "
                    f"{grade.name}."
                )
            )

        item_key = (service.id, grade.id, product.id)

        if item_key in seen_items:
            raise CommercialProjectionError(
                (
                    f"{product.name} está repetido en "
                    f"{service.level.name} - {grade.name}."
                )
            )

        seen_items.add(item_key)

        raw_quantity = payload.get("quantity")

        if raw_quantity is None:
            quantity = prepared_grades[grade_key]["student_count"]
        else:
            quantity = _positive_int(
                raw_quantity,
                field_label="Cantidad proyectada",
            )

        price = resolve_projection_price(
            product=product,
            campaign=locked_opportunity.campaign,
        )

        prepared_items.append(
            {
                "grade_key": grade_key,
                "product": product,
                "quantity": quantity,
                "unit_price": price.price,
                "price_year_snapshot": price.year,
                "price_campaign_snapshot": price.campaign,
            }
        )

    current_version = (
        locked_opportunity.projections
        .aggregate(max_version=Max("version"))
        .get("max_version")
        or 0
    )

    locked_opportunity.projections.filter(
        is_current=True,
    ).update(
        is_current=False,
        updated_at=timezone.now(),
    )

    projection = CommercialProjection(
        opportunity=locked_opportunity,
        version=current_version + 1,
        is_current=True,
        school_name_snapshot=locked_opportunity.school.name,
        campaign_name_snapshot=locked_opportunity.campaign.name,
        campaign_year_snapshot=locked_opportunity.campaign.year,
        notes=(notes or "").strip(),
        created_by=actor,
    )
    projection.full_clean()
    projection.save()

    grade_objects = {}

    for key, prepared in prepared_grades.items():
        grade_line = CommercialProjectionGrade(
            projection=projection,
            service=prepared["service"],
            grade=prepared["grade"],
            level_name_snapshot=prepared["service"].level.name,
            grade_name_snapshot=prepared["grade"].name,
            section_count=prepared["section_count"],
            student_count=prepared["student_count"],
        )
        grade_line.full_clean()
        grade_line.save()
        grade_objects[key] = grade_line

    for prepared in prepared_items:
        product = prepared["product"]
        item = CommercialProjectionItem(
            projection=projection,
            grade_line=grade_objects[prepared["grade_key"]],
            product=product,
            quantity=prepared["quantity"],
            unit_price=prepared["unit_price"],
            price_year_snapshot=prepared["price_year_snapshot"],
            price_campaign_snapshot=prepared[
                "price_campaign_snapshot"
            ],
            **_product_snapshot(product),
        )
        item.full_clean()
        item.save()

    return (
        CommercialProjection.objects
        .select_related(
            "opportunity",
            "created_by",
        )
        .prefetch_related(
            "grades__service__level",
            "grades__grade",
            "items__grade_line",
            "items__product__provider",
            "items__product__level",
            "items__product__grade",
            "items__product__area",
        )
        .get(pk=projection.pk)
    )
