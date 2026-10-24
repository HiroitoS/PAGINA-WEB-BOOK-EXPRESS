"""Reglas transaccionales de Recepción de Mercadería.

Los saldos se calculan a partir de recepciones VALIDADAS; no de movimientos
de stock, ventas ni facturas. No se permite sobre-recepción aceptada sin
un flujo formal de excepción que se diseñará posteriormente.
"""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Trim, Upper
from django.utils import timezone

from accounts.permissions import usuario_tiene_permiso
from catalog.models import Provider
from purchasing.models import PurchaseOrder, PurchaseOrderEvent, PurchaseOrderItem
from warehouse.models import GoodsReceipt, GoodsReceiptEvent, GoodsReceiptLine


def _autorizar(actor, permiso):
    if not actor or not actor.is_authenticated or not usuario_tiene_permiso(actor, permiso):
        raise PermissionDenied("No tienes permiso para realizar esta operación.")


def _normalizar_documento(document_type, document_number):
    numero = str(document_number or "").strip().upper()
    if document_type == GoodsReceipt.DocumentType.GUIDE and not numero:
        raise ValidationError(
            "La guía de remisión debe tener una serie y número válidos."
        )
    return numero


def _validar_guia_no_duplicada(*, provider_id, document_type, document_number, excluir_id=None):
    if document_type != GoodsReceipt.DocumentType.GUIDE:
        return
    existentes = (
        GoodsReceipt.objects.filter(
            provider_id=provider_id,
            document_type=GoodsReceipt.DocumentType.GUIDE,
        ).annotate(numero_normalizado=Upper(Trim("document_number")))
        .filter(numero_normalizado=document_number)
    )
    if excluir_id:
        existentes = existentes.exclude(pk=excluir_id)
    if existentes.exists():
        raise ValidationError(
            "Esta guía de remisión ya está registrada para esta editorial. "
            "Abre la recepción existente en lugar de crear otra."
        )


@transaction.atomic
def crear_borrador_recepcion(
    *, actor, provider_id, document_type, document_number,
    received_on, lines, notes="",
):
    _autorizar(actor, "warehouse.manage_receiving")
    if not lines:
        raise ValidationError("La recepción debe contener al menos un producto.")
    ids = [line["order_item_id"] for line in lines]
    if len(set(ids)) != len(ids):
        raise ValidationError("No puedes repetir una línea del pedido en una recepción.")
    provider = Provider.objects.get(pk=provider_id)
    detalles = {
        item.pk: item for item in PurchaseOrderItem.objects.select_related("order")
        .filter(pk__in=ids)
    }
    if len(detalles) != len(ids):
        raise ValidationError("Algunos productos del pedido no existen.")
    for row in lines:
        item = detalles[row["order_item_id"]]
        if item.order.provider_id != provider.pk:
            raise ValidationError("Todos los productos deben pertenecer a la misma editorial.")
        if item.order.status not in (
            PurchaseOrder.Status.SENT,
            PurchaseOrder.Status.PARTIALLY_RECEIVED,
        ):
            raise ValidationError("Solo puedes recepcionar pedidos enviados y aún pendientes.")
        if row["quantity_arrived"] != row["quantity_accepted"] + row["quantity_observed"] + row["quantity_extra"]:
            raise ValidationError("Cantidad llegada debe ser igual a aceptada más observada.")
    documento = _normalizar_documento(document_type, document_number)
    _validar_guia_no_duplicada(
        provider_id=provider.pk, document_type=document_type,
        document_number=documento,
    )
    recepcion = GoodsReceipt(
        provider=provider,
        document_type=document_type,
        document_number=documento,
        received_on=received_on,
        notes=notes.strip(),
        created_by=actor,
    )
    recepcion.full_clean()
    recepcion.save()
    for row in lines:
        linea = GoodsReceiptLine(
            receipt=recepcion,
            order_item=detalles[row["order_item_id"]],
            quantity_arrived=row["quantity_arrived"],
            quantity_accepted=row["quantity_accepted"],
            quantity_observed=row["quantity_observed"],
            quantity_documented=row.get("quantity_documented"),
            quantity_extra=row["quantity_extra"],
            notes=row.get("notes", "").strip(),
        )
        linea.full_clean()
        linea.save()
    GoodsReceiptEvent.objects.create(
        receipt=recepcion, actor=actor, action="created",
        details={"items": len(lines)},
    )
    return recepcion


@transaction.atomic
def actualizar_borrador_recepcion(
    *, actor, receipt_id, provider_id, document_type,
    document_number, received_on, lines, notes="",
):
    _autorizar(actor, "warehouse.manage_receiving")
    recepcion = GoodsReceipt.objects.select_for_update().get(pk=receipt_id)
    if recepcion.status != GoodsReceipt.Status.DRAFT:
        raise ValidationError("Solo se puede modificar una recepción en borrador.")
    if recepcion.provider_id != provider_id:
        raise ValidationError("No puedes cambiar la editorial de una recepción existente.")
    if not lines:
        raise ValidationError("La recepción necesita al menos una línea.")
    ids = [row["order_item_id"] for row in lines]
    if len(ids) != len(set(ids)):
        raise ValidationError("No puedes repetir un producto del mismo pedido.")
    detalles = {
        item.pk: item for item in PurchaseOrderItem.objects.select_related("order")
        .filter(pk__in=ids)
    }
    if len(detalles) != len(ids):
        raise ValidationError("Algunos productos no existen.")
    for row in lines:
        item = detalles[row["order_item_id"]]
        if item.order.provider_id != recepcion.provider_id:
            raise ValidationError("Los productos deben pertenecer a la editorial.")
        if item.order.status not in (
            PurchaseOrder.Status.SENT,
            PurchaseOrder.Status.PARTIALLY_RECEIVED,
        ):
            raise ValidationError("Solo puedes recepcionar pedidos enviados y pendientes.")
        if row["quantity_arrived"] != row["quantity_accepted"] + row["quantity_observed"] + row["quantity_extra"]:
            raise ValidationError("La cantidad llegada no coincide con aceptada más observada.")

    documento = _normalizar_documento(document_type, document_number)
    _validar_guia_no_duplicada(
        provider_id=recepcion.provider_id, document_type=document_type,
        document_number=documento, excluir_id=recepcion.pk,
    )
    estado_previo = {
        "document_type": recepcion.document_type,
        "document_number": recepcion.document_number,
        "received_on": str(recepcion.received_on),
        "notes": recepcion.notes,
        "lines": list(recepcion.lines.values(
            "order_item_id", "quantity_arrived", "quantity_accepted",
            "quantity_observed", "quantity_documented", "quantity_extra", "notes",
        )),
    }
    recepcion.document_type = document_type
    recepcion.document_number = documento
    recepcion.received_on = received_on
    recepcion.notes = notes.strip()
    recepcion.full_clean()
    recepcion.save(update_fields=[
        "document_type", "document_number", "received_on", "notes", "updated_at",
    ])
    recepcion.lines.all().delete()
    for row in lines:
        detalle = GoodsReceiptLine(
            receipt=recepcion,
            order_item=detalles[row["order_item_id"]],
            quantity_arrived=row["quantity_arrived"],
            quantity_accepted=row["quantity_accepted"],
            quantity_observed=row["quantity_observed"],
            quantity_documented=row.get("quantity_documented"),
            quantity_extra=row["quantity_extra"],
            notes=row.get("notes", "").strip(),
        )
        detalle.full_clean()
        detalle.save()
    GoodsReceiptEvent.objects.create(
        receipt=recepcion, actor=actor, action="updated",
        details={
            "before": estado_previo,
            "after": {
                "document_type": document_type,
                "document_number": documento,
                "received_on": str(received_on),
                "items": len(lines),
                "lines": [
                    {
                        "order_item_id": row["order_item_id"],
                        "quantity_arrived": row["quantity_arrived"],
                        "quantity_accepted": row["quantity_accepted"],
                        "quantity_observed": row["quantity_observed"],
                        "quantity_documented": row.get("quantity_documented"),
                        "quantity_extra": row["quantity_extra"],
                    } for row in lines
                ],
            },
        },
    )
    return recepcion


@transaction.atomic
def validar_recepcion(*, actor, receipt_id):
    _autorizar(actor, "warehouse.validate_receiving")
    receipt = GoodsReceipt.objects.select_for_update().get(pk=receipt_id)
    if receipt.status != GoodsReceipt.Status.DRAFT:
        raise ValidationError("Esta recepción ya fue validada.")
    if not receipt.document_number.strip():
        raise ValidationError("Registra el número del documento del proveedor.")

    filas = list(
        GoodsReceiptLine.objects.select_related("order_item__order")
        .filter(receipt=receipt).order_by("pk")
    )
    if not filas:
        raise ValidationError("Una recepción sin productos no puede validarse.")
    ids_pedidos = sorted({fila.order_item.order_id for fila in filas})
    pedidos = {
        item.pk: item for item in PurchaseOrder.objects.select_for_update()
        .filter(pk__in=ids_pedidos).order_by("pk")
    }
    for pedido in pedidos.values():
        if pedido.provider_id != receipt.provider_id or pedido.status not in (
            PurchaseOrder.Status.SENT, PurchaseOrder.Status.PARTIALLY_RECEIVED,
        ):
            raise ValidationError("Hay un pedido que no está pendiente de recepción.")

    ids_lineas = [fila.order_item_id for fila in filas]
    anteriores = {
        row["order_item_id"]: row["total"] for row in
        GoodsReceiptLine.objects.filter(
            order_item_id__in=ids_lineas,
            receipt__status=GoodsReceipt.Status.VALIDATED,
        ).values("order_item_id").annotate(total=Sum("quantity_accepted"))
    }
    for fila in filas:
        if fila.quantity_arrived != fila.quantity_accepted + fila.quantity_observed + fila.quantity_extra:
            raise ValidationError("Hay cantidades de recepción que no cuadran.")
        anterior_aceptado = anteriores.get(fila.order_item_id, 0)
        pendiente = max(0, fila.order_item.quantity_ordered - anterior_aceptado)
        if fila.quantity_accepted > pendiente:
            raise ValidationError(
                f"Se excede la cantidad solicitada para {fila.order_item.product_name_snapshot}."
            )
        if fila.quantity_documented is not None and fila.quantity_documented != fila.quantity_arrived and not (fila.notes.strip() or receipt.notes.strip()):
            raise ValidationError("Explica la diferencia entre la guía y el conteo físico.")
        if fila.quantity_extra and not (fila.notes.strip() or receipt.notes.strip()):
            raise ValidationError("Indica el motivo del excedente conforme conservado.")
        # Un excedente físico se registra como observado, nunca como compra
        # adicional ni stock disponible. Exigir una explicación verificable.
        if fila.quantity_arrived > pendiente and not (
            fila.notes.strip() or receipt.notes.strip()
        ):
            raise ValidationError(
                f"Registra en observaciones el motivo del excedente recibido de "
                f"{fila.order_item.product_name_snapshot}. "
                "Las unidades adicionales deben quedar identificadas como excedentes conformes u observadas."
            )

    receipt.status = GoodsReceipt.Status.VALIDATED
    receipt.validated_by = actor
    receipt.validated_at = timezone.now()
    receipt.save(update_fields=["status", "validated_by", "validated_at", "updated_at"])
    GoodsReceiptEvent.objects.create(
        receipt=receipt, actor=actor, action="validated",
        details={
            "accepted": sum(row.quantity_accepted for row in filas),
            "observed": sum(row.quantity_observed for row in filas),
            "extra": sum(row.quantity_extra for row in filas),
        },
    )

    for pedido in pedidos.values():
        lineas_pedido = list(
            PurchaseOrderItem.objects.filter(order=pedido).only("id", "quantity_ordered")
        )
        total_aceptado = {
            row["order_item_id"]: row["total"] for row in
            GoodsReceiptLine.objects.filter(
                order_item__order=pedido,
                receipt__status=GoodsReceipt.Status.VALIDATED,
            ).values("order_item_id").annotate(total=Sum("quantity_accepted"))
        }
        if all(total_aceptado.get(item.pk, 0) == item.quantity_ordered for item in lineas_pedido):
            estado_nuevo = PurchaseOrder.Status.RECEIVED
        elif any(total_aceptado.values()):
            estado_nuevo = PurchaseOrder.Status.PARTIALLY_RECEIVED
        else:
            estado_nuevo = pedido.status
        if estado_nuevo != pedido.status:
            anterior = pedido.status
            pedido.status = estado_nuevo
            pedido.save(update_fields=["status", "updated_at"])
            PurchaseOrderEvent.objects.create(
                order=pedido, actor=actor, event_type="receipt_validated",
                from_status=anterior, to_status=estado_nuevo,
                details={"receipt_id": receipt.pk},
            )
    return receipt


def saldos_pedido(*, actor, order_id):
    _autorizar(actor, "warehouse.view_receiving")
    pedido = PurchaseOrder.objects.get(pk=order_id)
    lineas = PurchaseOrderItem.objects.filter(order=pedido)
    aceptadas = {
        row["order_item_id"]: row["total"] for row in
        GoodsReceiptLine.objects.filter(
            order_item__order=pedido,
            receipt__status=GoodsReceipt.Status.VALIDATED,
        ).values("order_item_id").annotate(total=Sum("quantity_accepted"))
    }
    return {
        "pedido_id": pedido.pk,
        "editorial": pedido.provider_name_snapshot,
        "colegio": pedido.school_name_snapshot,
        "estado_pedido": pedido.status,
        "productos": [
            {
                "item_id": item.pk,
                "producto": item.product_name_snapshot,
                "cantidad_solicitada": item.quantity_ordered,
                "cantidad_aceptada": aceptadas.get(item.pk, 0),
                "cantidad_pendiente": max(0, item.quantity_ordered - aceptadas.get(item.pk, 0)),
            }
            for item in lineas
        ],
    }


def seguimiento_recepcion(*, actor, receipt):
    """Estado ACTUAL de los pedidos de una guía e historial de entregas validadas.

    La recepción seleccionada no cambia de contenido; el pendiente puede
    cambiar cuando otra guía posterior completa el mismo pedido.
    """
    _autorizar(actor, "warehouse.view_receiving")
    lineas_actuales = list(
        receipt.lines.select_related("order_item__order").order_by("pk")
    )
    ids_pedidos = sorted({line.order_item.order_id for line in lineas_actuales})
    if not ids_pedidos:
        return {"pedidos": []}

    items = list(
        PurchaseOrderItem.objects.select_related("order")
        .filter(order_id__in=ids_pedidos).order_by("order_id", "pk")
    )
    actual_por_item = {line.order_item_id: line for line in lineas_actuales}
    validadas = list(
        GoodsReceiptLine.objects.select_related("receipt", "order_item")
        .filter(
            order_item__order_id__in=ids_pedidos,
            receipt__status=GoodsReceipt.Status.VALIDATED,
        )
        .order_by("receipt__validated_at", "receipt_id", "pk")
    )
    aceptadas_por_item = {}
    entregas_por_pedido = {}
    for line in validadas:
        item_id = line.order_item_id
        aceptadas_por_item[item_id] = (
            aceptadas_por_item.get(item_id, 0) + line.quantity_accepted
        )
        # Múltiples productos de un mismo pedido pueden llegar en una sola guía:
        # agrupar por (pedido, recepción), sin duplicar esa entrega.
        pedido_id = line.order_item.order_id
        clave = (pedido_id, line.receipt_id)
        if clave not in entregas_por_pedido:
            entregas_por_pedido[clave] = {
                "receipt_id": line.receipt_id,
                "document_number": line.receipt.document_number,
                "received_on": line.receipt.received_on,
                "validated_at": line.receipt.validated_at,
                "llegaron": 0,
                "aceptadas": 0,
                "observadas": 0,
                "excedentes": 0,
                "es_recepcion_actual": line.receipt_id == receipt.pk,
            }
        registro = entregas_por_pedido[clave]
        registro["llegaron"] += line.quantity_arrived
        registro["aceptadas"] += line.quantity_accepted
        registro["observadas"] += line.quantity_observed
        registro["excedentes"] += line.quantity_extra

    por_pedido = {}
    for item in items:
        order = item.order
        if order.pk not in por_pedido:
            por_pedido[order.pk] = {
                "pedido_id": order.pk,
                "referencia": f"BE-OC-{order.pk:06d}",
                "colegio": order.school_name_snapshot or "Pedido independiente",
                "solicitadas": 0,
                "aceptadas": 0,
                "pendientes": 0,
                "productos": [],
                "entregas": [],
            }
        resumen = por_pedido[order.pk]
        aceptadas = aceptadas_por_item.get(item.pk, 0)
        pendiente = max(0, item.quantity_ordered - aceptadas)
        linea_actual = actual_por_item.get(item.pk)
        resumen["solicitadas"] += item.quantity_ordered
        resumen["aceptadas"] += aceptadas
        resumen["pendientes"] += pendiente
        resumen["productos"].append({
            "item_id": item.pk,
            "producto": item.product_name_snapshot,
            "codigo": item.product_code_snapshot,
            "solicitadas": item.quantity_ordered,
            "aceptadas_acumuladas": aceptadas,
            "pendientes": pendiente,
            "llegaron_en_guia": linea_actual.quantity_arrived if linea_actual else 0,
            "aceptadas_en_guia": linea_actual.quantity_accepted if linea_actual else 0,
            "observadas_en_guia": linea_actual.quantity_observed if linea_actual else 0,
            "documentadas_en_guia": linea_actual.quantity_documented if linea_actual else None,
            "excedentes_en_guia": linea_actual.quantity_extra if linea_actual else 0,
        })

    for (pedido_id, _), entrega in entregas_por_pedido.items():
        por_pedido[pedido_id]["entregas"].append(entrega)
    return {"pedidos": list(por_pedido.values())}
