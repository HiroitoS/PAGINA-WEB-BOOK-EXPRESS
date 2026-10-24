"""Orden de compra PDF generada desde el pedido aprobado, sin alterar su estado."""
from decimal import Decimal
from html import escape
from io import BytesIO

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)


ROJO = colors.HexColor("#BA1021")
GRIS = colors.HexColor("#515B6B")
CLARO = colors.HexColor("#F4F5F7")


def _parrafo(value, style):
    return Paragraph(escape(str(value or "")), style)


def _importe(value):
    return f"{Decimal(value):,.2f}"


def generar_orden_compra_pdf(pedido):
    """Construye el documento a partir de snapshots y cantidades del pedido."""
    buffer = BytesIO()
    documento = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=20 * mm, bottomMargin=19 * mm,
        title=f"Orden de compra BE-OC-{pedido.pk:06d}",
        author="Distribuidora y Comercializadora Book Express SAC",
    )
    ancho = A4[0] - 36 * mm
    titulo = ParagraphStyle(
        "Titulo", fontName="Helvetica-Bold", fontSize=16,
        leading=20, textColor=ROJO, spaceAfter=4,
    )
    principal = ParagraphStyle(
        "Principal", fontName="Helvetica", fontSize=9,
        leading=13, textColor=colors.black,
    )
    pequeno = ParagraphStyle(
        "Pequeno", parent=principal, fontSize=8,
        leading=11, textColor=GRIS,
    )
    encabezado = ParagraphStyle(
        "Encabezado", parent=pequeno, fontName="Helvetica-Bold",
        textColor=colors.white,
    )
    derecha = ParagraphStyle("Derecha", parent=principal, alignment=TA_RIGHT)
    pie = ParagraphStyle("Pie", parent=pequeno, alignment=TA_CENTER)
    items = list(pedido.items.all().order_by("pk"))
    monedas = sorted({item.currency for item in items})
    if not items:
        raise ValueError("No es posible emitir una orden sin productos.")
    if len(monedas) != 1:
        raise ValueError("La orden contiene monedas diferentes.")
    moneda = monedas[0]

    fecha = timezone.localtime(pedido.approved_at or pedido.created_at)
    contenido = [
        Paragraph("BOOK EXPRESS", titulo),
        _parrafo("Distribuidora y Comercializadora Book Express SAC · RUC 20601658811", pequeno),
        Spacer(1, 10),
        Paragraph("ORDEN DE COMPRA A EDITORIAL", titulo),
        _parrafo(f"Número: BE-OC-{pedido.pk:06d} · Fecha de aprobación: {fecha:%d/%m/%Y}", principal),
        Spacer(1, 9),
    ]
    datos = [
        [_parrafo("Editorial", pequeno), _parrafo(pedido.provider_name_snapshot, principal)],
        [_parrafo("Colegio", pequeno), _parrafo(pedido.school_name_snapshot or "Compra independiente", principal)],
        [_parrafo("Campaña", pequeno), _parrafo(pedido.campaign_name_snapshot, principal)],
        [_parrafo("Referencia interna", pequeno), _parrafo(str(pedido.reference), pequeno)],
    ]
    tabla_datos = Table(datos, colWidths=[110, ancho - 110], hAlign="LEFT")
    tabla_datos.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.HexColor("#D8DBE0")),
    ]))
    contenido += [tabla_datos, Spacer(1, 15)]
    tabla_items = [[
        _parrafo("N°", encabezado), _parrafo("Código", encabezado),
        _parrafo("Libro / material", encabezado),
        _parrafo("Cant.", encabezado),
        _parrafo(f"Costo ({moneda})", encabezado),
        _parrafo(f"Importe ({moneda})", encabezado),
    ]]
    total = Decimal("0.00")
    for numero, item in enumerate(items, 1):
        subtotal = item.unit_supplier_cost * item.quantity_ordered
        total += subtotal
        tabla_items.append([
            _parrafo(numero, pequeno),
            _parrafo(item.product_code_snapshot or "—", pequeno),
            _parrafo(item.product_name_snapshot, principal),
            _parrafo(item.quantity_ordered, derecha),
            _parrafo(_importe(item.unit_supplier_cost), derecha),
            _parrafo(_importe(subtotal), derecha),
        ])
    anchos = [24, 75, ancho - 24 - 75 - 43 - 75 - 78, 43, 75, 78]
    detalle = LongTable(tabla_items, repeatRows=1, colWidths=anchos, hAlign="LEFT")
    detalle.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ROJO),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, CLARO]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, ROJO),
    ]))
    contenido += [detalle, Spacer(1, 12)]
    total_tabla = Table([
        [_parrafo(f"TOTAL ORDEN ({moneda})", encabezado), _parrafo(_importe(total), encabezado)]
    ], colWidths=[ancho - 140, 140])
    total_tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#292B32")),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    contenido.extend([
        total_tabla, Spacer(1, 15),
        _parrafo("Documento emitido por Book Express. El registro de envío a la editorial se realiza por separado.", pequeno),
        Spacer(1, 15),
        _parrafo("Orden de compra aprobada · Documento para remisión manual a la editorial.", pie),
    ])

    def dibujar_pie(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D8DBE0"))
        canvas.line(18 * mm, 15 * mm, A4[0] - 18 * mm, 15 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(GRIS)
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Página {doc.page}")
        canvas.restoreState()

    documento.build(contenido, onFirstPage=dibujar_pie, onLaterPages=dibujar_pie)
    return buffer.getvalue()
