"""Evidencias privadas y comunicaciones con editoriales por recepción validada."""
import mimetypes
from uuid import UUID

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Sum
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from warehouse.models import (
    GoodsReceipt, GoodsReceiptEvent, GoodsReceiptLine, ReceivingEvidence,
)

MAX_BYTES = 8 * 1024 * 1024
ALLOWED = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".pdf": "application/pdf",
}


class EvidenceInput(serializers.Serializer):
    receipt_line_id = serializers.IntegerField(min_value=1)
    kind = serializers.ChoiceField(choices=ReceivingEvidence.Kind.choices)
    description = serializers.CharField(min_length=8, max_length=500)
    file = serializers.FileField(allow_empty_file=False)

    def validate_file(self, file):
        from pathlib import Path
        suffix = Path(file.name).suffix.lower()
        if suffix not in ALLOWED or file.size > MAX_BYTES:
            raise serializers.ValidationError(
                "Adjunta una imagen JPG, PNG, WEBP o PDF de hasta 8 MB."
            )
        magic = file.read(16)
        file.seek(0)
        recognized = (
            suffix in (".jpg", ".jpeg") and magic.startswith(b"\xff\xd8\xff")
            or suffix == ".png" and magic.startswith(b"\x89PNG\r\n\x1a\n")
            or suffix == ".webp" and magic[:4] == b"RIFF" and magic[8:12] == b"WEBP"
            or suffix == ".pdf" and magic.startswith(b"%PDF-")
        )
        if not recognized:
            raise serializers.ValidationError("El archivo no coincide con el formato indicado.")
        return file


def evidence_dict(e):
    return {
        "id": e.pk, "receipt_line_id": e.receipt_line_id,
        "product": e.receipt_line.order_item.product_name_snapshot,
        "kind": e.kind, "kind_label": e.get_kind_display(),
        "description": e.description, "original_name": e.original_name,
        "created_by": e.created_by.get_username(), "created_at": e.created_at,
        "download_path": (
            f"/admin/erp/almacen/recepciones/{e.receipt_line.receipt_id}/"
            f"evidencias/{e.pk}/archivo/"
        ),
    }


def evidence_list(receipt):
    return [
        evidence_dict(e) for e in ReceivingEvidence.objects.filter(
            receipt_line__receipt=receipt,
        ).select_related("receipt_line__order_item", "created_by")
    ]


def guardar_evidencia(*, receipt, actor, data):
    form = EvidenceInput(data=data)
    form.is_valid(raise_exception=True)
    fields = form.validated_data
    if receipt.status == GoodsReceipt.Status.CANCELLED:
        raise ValidationError("La recepción anulada no permite adjuntar evidencias.")
    line = get_object_or_404(
        GoodsReceiptLine, pk=fields["receipt_line_id"], receipt=receipt,
    )
    if fields["kind"] in (
        ReceivingEvidence.Kind.DAMAGED, ReceivingEvidence.Kind.INCORRECT,
    ) and not line.quantity_observed:
        raise ValidationError(
            "Marca los libros deteriorados o incorrectos como Observados antes de adjuntar evidencia."
        )
    if fields["kind"] == ReceivingEvidence.Kind.SHORTAGE and (
        line.quantity_documented is None
        or line.quantity_documented <= line.quantity_arrived
    ):
        raise ValidationError("La guía no registra faltante físico para este libro.")
    return ReceivingEvidence.objects.create(
        receipt_line=line, kind=fields["kind"],
        description=fields["description"].strip(),
        file=fields["file"],
        original_name=fields["file"].name[:220],
        created_by=actor,
    )


def protected_download(*, receipt, evidence_id):
    e = get_object_or_404(
        ReceivingEvidence, pk=evidence_id, receipt_line__receipt=receipt,
    )
    content_type = mimetypes.guess_type(e.original_name)[0] or "application/octet-stream"
    return FileResponse(
        e.file.open("rb"), as_attachment=True, filename=e.original_name,
        content_type=content_type,
    )


def construir_reporte(receipt):
    lines = list(receipt.lines.select_related(
        "order_item__order", "order_item__product",
    ).order_by("pk"))
    evidences = evidence_list(receipt)
    details = []
    affected = set()
    for row in lines:
        guide_shortage = max(0, (row.quantity_documented or 0) - row.quantity_arrived)
        if guide_shortage or row.quantity_observed:
            affected.add(row.pk)
            details.append(
                f"- {row.order_item.product_name_snapshot} "
                f"(pedido BE-OC-{row.order_item.order_id:06d}, "
                f"colegio {row.order_item.order.school_name_snapshot or 'Sin colegio'}): "
                f"guía {row.quantity_documented if row.quantity_documented is not None else 'No consignado'}, "
                f"físico {row.quantity_arrived}, observados {row.quantity_observed}, "
                f"faltantes frente a guía {guide_shortage}."
            )
    extra_lines = [
        f"- {e['product']}: {e['kind_label']} — {e['description']} (archivo {e['original_name']})"
        for e in evidences
    ]
    # Pendiente respecto del pedido no equivale a faltante físico respecto de esta guía.
    if not details:
        details.append("No se detectaron diferencias frente al documento en esta recepción.")
    subject = (
        f"Book Express | Reporte de recepción {receipt.document_number} "
        f"| {receipt.provider.name}"
    )
    body = "\n".join([
        "Estimados señores:",
        "",
        f"Compartimos las observaciones de la recepción de {receipt.provider.name}, "
        f"documento {receipt.document_number}, fecha {receipt.received_on}.",
        "",
        "Diferencias físicas verificadas:",
        *details,
        "",
        "Evidencias documentales:",
        *(extra_lines or ["No se adjuntaron evidencias."]),
        "",
        "Agradeceremos su revisión y respuesta indicando el tratamiento de las diferencias.",
        "",
        "Distribuidora y Comercializadora Book Express S.A.C.",
    ])
    return {
        "receipt_id": receipt.pk, "subject": subject, "body": body,
        "evidences": evidences, "requires_attention": bool(affected or evidences),
        "validated": receipt.status == GoodsReceipt.Status.VALIDATED,
        "sending_enabled": bool(
            getattr(settings, "ERP_WAREHOUSE_SUPPLIER_EMAIL_ENABLED", False)
            and getattr(settings, "DEFAULT_FROM_EMAIL", "")
            and getattr(settings, "EMAIL_HOST", "")
        ),
        "notice": (
            "Un pedido con saldo pendiente no es necesariamente un faltante frente a la guía. "
            "El reporte requiere revisión antes de enviarlo."
        ),
    }


@transaction.atomic
def enviar_reporte_editorial(*, receipt_id, actor, recipient, dispatch_key):
    """Envío explícito autenticado; sin SMTP habilitado nunca afirma envío."""
    if not (
        getattr(settings, "ERP_WAREHOUSE_SUPPLIER_EMAIL_ENABLED", False)
        and getattr(settings, "DEFAULT_FROM_EMAIL", "")
        and getattr(settings, "EMAIL_HOST", "")
    ):
        raise ValidationError("Configura primero el correo corporativo de envío a editoriales.")
    try:
        request_key = str(UUID(str(dispatch_key)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("Referencia de envío inválida.") from exc
    receipt = get_object_or_404(
        GoodsReceipt.objects.select_for_update().select_related("provider"),
        pk=receipt_id,
    )
    if receipt.status != GoodsReceipt.Status.VALIDATED:
        raise ValidationError("El reporte formal se envía después de aprobar la recepción.")
    existing = GoodsReceiptEvent.objects.filter(
        receipt=receipt, action="supplier_report_sent",
        details__dispatch_key=request_key,
    ).first()
    if existing:
        if existing.details.get("recipient") != recipient:
            raise ValidationError("Esta referencia de envío corresponde a otro destinatario.")
        return {"sent": True, "repeated": True, "event_id": existing.pk}
    report = construir_reporte(receipt)
    if not report["requires_attention"]:
        raise ValidationError("No hay observaciones o evidencias que justifiquen el reporte.")
    evidence_rows = list(ReceivingEvidence.objects.filter(
        receipt_line__receipt=receipt,
    ).select_related("receipt_line")[:16])
    if len(evidence_rows) > 12 or sum(e.file.size for e in evidence_rows) > 18 * 1024 * 1024:
        raise ValidationError("Reduce los anexos a 12 archivos y 18 MB por correo.")
    email = EmailMessage(
        report["subject"], report["body"],
        settings.DEFAULT_FROM_EMAIL, [recipient],
    )
    for evidence in evidence_rows:
        evidence.file.open("rb")
        try:
            email.attach(
                evidence.original_name, evidence.file.read(),
                mimetypes.guess_type(evidence.original_name)[0] or "application/octet-stream",
            )
        finally:
            evidence.file.close()
    try:
        sent = email.send(fail_silently=False)
    except Exception as exc:
        raise ValidationError("No se pudo enviar el correo. Revisa la configuración SMTP.") from exc
    if sent != 1:
        raise ValidationError("El servicio de correo no confirmó el envío.")
    event = GoodsReceiptEvent.objects.create(
        receipt=receipt, actor=actor, action="supplier_report_sent",
        details={
            "dispatch_key": request_key, "recipient": recipient,
            "attachment_count": len(evidence_rows),
        },
    )
    return {"sent": True, "repeated": False, "event_id": event.pk}
