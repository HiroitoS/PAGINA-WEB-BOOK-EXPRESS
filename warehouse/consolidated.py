"""Consulta consolidada de existencias por editorial, colegio de origen o ubicación.

No crea movimientos ni considera que el stock llegado por un colegio esté
reservado para él. Cada ejemplar conforme cuenta una sola vez, independientemente
de los traslados internos. Los observados se contabilizan por separado.
"""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.core.paginator import EmptyPage, Paginator
from django.db.models import Q, Sum
from rest_framework.exceptions import ValidationError

from warehouse.models import StockEntry, StockMovement, WarehouseLocation
from warehouse.transfers import posiciones_lotes


GROUPS = {"editorial", "colegio", "almacen"}


def consultar_consolidado(*, grupo="editorial", query="", page=1, provider_id=None):
    if grupo not in GROUPS:
        raise ValidationError({"grupo": "Selecciona editorial, colegio o almacén."})
    if not isinstance(page, int) or page < 1:
        raise ValidationError({"pagina": "Selecciona una página válida."})
    if len(query) > 100:
        raise ValidationError({"buscar": "La búsqueda debe tener como máximo 100 caracteres."})

    qs = StockEntry.objects.select_related(
        "initial_location__location", "product__provider",
        "receipt_line__receipt", "receipt_line__order_item__order__school",
    ).order_by("pk")
    if provider_id is not None:
        qs = qs.filter(product__provider_id=provider_id)
    if query:
        qs = qs.filter(
            Q(product__name__icontains=query)
            | Q(product__code__icontains=query)
            | Q(product__provider__name__icontains=query)
            | Q(receipt_line__order_item__order__school_name_snapshot__icontains=query)
            | Q(receipt_line__receipt__document_number__icontains=query)
        )
    entries = list(qs)
    positions = posiciones_lotes(entries)
    move_totals = {
        item["source_entry_id"]: item["total"]
        for item in StockMovement.objects.filter(
            source_entry_id__in=[entry.pk for entry in entries],
        ).values("source_entry_id").annotate(total=Sum("quantity_delta"))
    }
    locations = {
        loc.pk: loc.name for loc in WarehouseLocation.objects.all()
    }
    positions_by_entry = defaultdict(list)
    for (entry_id, location_id), amount in positions.items():
        if amount > 0:
            positions_by_entry[entry_id].append((location_id, amount))
    rows = {}
    unreconciled = 0

    def add(entry, *, location_id, available=0, observed=0):
        if not available and not observed:
            return
        item = entry.receipt_line.order_item
        order = item.order
        provider = entry.product.provider
        if grupo == "editorial":
            dimension_id = provider.pk
            dimension_name = provider.name
        elif grupo == "colegio":
            dimension_id = order.school_id
            # El nombre de referencia es histórico y puede ser más fiable
            # que el nombre actual del colegio.
            dimension_name = (
                order.school_name_snapshot
                or (order.school.name if order.school_id else "")
                or "Sin colegio de origen"
            )
        else:
            dimension_id = location_id
            dimension_name = locations.get(location_id, "Sin ubicación asignada")

        key = (dimension_id, dimension_name, entry.product_id)
        row = rows.setdefault(key, {
            "grupo_id": dimension_id,
            "grupo_nombre": dimension_name,
            "producto_id": entry.product_id,
            "producto": entry.product.name,
            "editorial": provider.name,
            "disponible": 0,
            "observado": 0,
            "valor_parcial": Decimal("0.00"),
            "unidades_sin_costo": 0,
        })
        row["disponible"] += available
        row["observado"] += observed
        if entry.unit_cost_snapshot is None:
            row["unidades_sin_costo"] += available
        else:
            row["valor_parcial"] += entry.unit_cost_snapshot * available

    for entry in entries:
        net = entry.quantity_available + (move_totals.get(entry.pk) or 0)
        if net < 0:
            raise ValidationError({
                "inventario": "Se detectó un saldo negativo. Revisa los movimientos del lote.",
            })
        placed = positions_by_entry.get(entry.pk, [])
        placed_total = sum(amount for _, amount in placed)
        for location_id, amount in placed:
            add(entry, location_id=location_id, available=amount)
        residual = net - placed_total
        if residual < 0:
            raise ValidationError({
                "inventario": "Los saldos por ubicación superan el inventario total. Revisa este lote.",
            })
        if residual:
            unreconciled += residual
            add(entry, location_id=None, available=residual)
        if entry.quantity_quarantined:
            assignment = getattr(entry, "initial_location", None)
            add(
                entry,
                location_id=assignment.location_id if assignment else None,
                observed=entry.quantity_quarantined,
            )

    result = []
    for row in rows.values():
        quantity = row["disponible"]
        complete = row["unidades_sin_costo"] == 0
        unit = (
            (row["valor_parcial"] / Decimal(quantity)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP,
            )
            if complete and quantity > 0 else None
        )
        result.append({
            "grupo_id": row["grupo_id"],
            "grupo_nombre": row["grupo_nombre"],
            "producto_id": row["producto_id"],
            "producto": row["producto"],
            "editorial": row["editorial"],
            "disponible": quantity,
            "observado": row["observado"],
            "costo_promedio": str(unit) if unit is not None else None,
            "valor_referencial": (
                str(row["valor_parcial"]) if complete else None
            ),
            "unidades_sin_costo": row["unidades_sin_costo"],
        })
    result.sort(key=lambda row: (
        row["grupo_nombre"].casefold(), row["producto"].casefold(),
        row["producto_id"],
    ))
    paginator = Paginator(result, 25)
    try:
        current = paginator.page(page)
    except EmptyPage:
        raise ValidationError({"pagina": "No existen resultados en esta página."})

    complete = all(row["unidades_sin_costo"] == 0 for row in rows.values())
    return {
        "grupo": grupo,
        "conteo": paginator.count,
        "pagina": current.number,
        "paginas": paginator.num_pages,
        "resultados": list(current.object_list),
        "resumen": {
            "disponible": sum(row["disponible"] for row in rows.values()),
            "observado": sum(row["observado"] for row in rows.values()),
            "valor_referencial": (
                str(sum(
                    (row["valor_parcial"] for row in rows.values()),
                    Decimal("0.00"),
                )) if complete else None
            ),
            "unidades_sin_costo": sum(
                row["unidades_sin_costo"] for row in rows.values()
            ),
            "unidades_sin_ubicacion": unreconciled,
            "valorizacion_completa": complete,
        },
        "nota": (
            "Por colegio se muestra el origen del pedido, no una reserva vigente. "
            "Los traslados no aumentan el inventario general. "
            "Los valores corresponden al costo histórico y no son deuda de editorial."
        ),
    }
