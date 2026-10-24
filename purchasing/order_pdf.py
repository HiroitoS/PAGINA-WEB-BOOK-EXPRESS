"""Documento formal de compra: refleja exclusivamente cantidades y costos aprobados."""
from decimal import Decimal
from html import escape
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROJO = colors.HexColor("#BA1021")
GRIS = colors.HexColor("#515B6B")
CLARO = colors.HexColor("#F4F5F7")
NEGRO = colors.HexColor("#292B32")
BORDE = colors.HexColor("#D8DBE0")
MARCA_LOGO = "logo-book-express-negro-recortado.png"


def _parrafo(value, style):
    return Paragraph(escape(str(value or "")), style)


def _importe(value):
    return f"{Decimal(value):,.2f}"


def _logo_oficial():
    """El mismo recurso gráfico que usa el panel, sin redibujar ni alterar la marca.

    En despliegues independientes, configurar BOOK_EXPRESS_LOGO_PATH o copiar
    el logo a assets/brand dentro del backend antes de publicar.
    """
    configurado = getattr(settings, "BOOK_EXPRESS_LOGO_PATH", None)
    rutas = [
        Path(configurado) if configurado else None,
        Path(settings.BASE_DIR) / "assets" / "brand" / MARCA_LOGO,
        Path(settings.BASE_DIR).parent / "bookexpress_frontend" / "src" / "assets" / "brand" / MARCA_LOGO,
    ]
    for ruta in rutas:
        if ruta and ruta.is_file():
            try:
                ancho, alto = ImageReader(str(ruta)).getSize()
                escala = min(35 * mm / ancho, 14 * mm / alto)
                return Image(str(ruta), width=ancho * escala, height=alto * escala)
            except (OSError, ValueError):
                continue
    return None


def generar_orden_compra_pdf(pedido):
    """Genera PDF A4 horizontal por colegio/editorial; no registra mercadería recibida."""
    detalles = list(pedido.items.all().order_by("pk"))
    if not detalles:
        raise ValueError("No es posible emitir una orden sin productos.")

    monedas = {detalle.currency for detalle in detalles}
    if len(monedas) != 1:
        raise ValueError("La orden contiene monedas diferentes.")
    moneda = monedas.pop()
    numero = f"BE-OC-{pedido.pk:06d}"
    fecha = timezone.localtime(pedido.approved_at or pedido.created_at)

    ancho_pagina, alto_pagina = landscape(A4)
    margen = 14 * mm
    ancho = ancho_pagina - 2 * margen
    buffer = BytesIO()
    documento = SimpleDocTemplate(
        buffer, pagesize=(ancho_pagina, alto_pagina),
        leftMargin=margen, rightMargin=margen,
        topMargin=13 * mm, bottomMargin=16 * mm,
        title=f"Orden de compra {numero}",
        author="Distribuidora y Comercializadora Book Express SAC",
    )
    titulo = ParagraphStyle(
        "TituloCompra", fontName="Helvetica-Bold", fontSize=12,
        leading=15, textColor=ROJO,
    )
    principal = ParagraphStyle(
        "TextoCompra", fontName="Helvetica", fontSize=8.2,
        leading=11, textColor=colors.black,
    )
    pequeno = ParagraphStyle(
        "TextoMenorCompra", parent=principal, fontSize=7.4,
        leading=9.5, textColor=GRIS,
    )
    encabezado = ParagraphStyle(
        "EncabezadoCompra", parent=pequeno, fontName="Helvetica-Bold",
        textColor=colors.white,
    )
    derecha = ParagraphStyle(
        "NumeroDerechaCompra", parent=principal, alignment=TA_RIGHT,
    )
    encabezado_derecha = ParagraphStyle(
        "EncabezadoDerechaCompra", parent=encabezado, alignment=TA_RIGHT,
    )

    logo = _logo_oficial()
    marca = logo or Paragraph("BOOK EXPRESS", titulo)
    emisor = Paragraph(
        "<b>Distribuidora y Comercializadora Book Express SAC</b>"
        "<br/>RUC 20601658811 · Huancayo, Junín, Perú",
        principal,
    )
    identificacion = Paragraph(
        f"<b>ORDEN DE COMPRA</b><br/>N.º {numero}"
        f"<br/><font size='8'>Aprobada: {fecha:%d/%m/%Y}</font>",
        principal,
    )
    cabecera = Table(
        [[marca, emisor, identificacion]],
        colWidths=[115, ancho - 115 - 235, 235],
        hAlign="LEFT",
    )
    cabecera.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (2, 0), (2, 0), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, -1), 1.2, ROJO),
    ]))

    def dato(etiqueta, valor):
        return Paragraph(f"<b>{escape(etiqueta)}:</b> {escape(str(valor or '—'))}", principal)

    informacion = Table([
        [
            dato("Editorial", pedido.provider_name_snapshot),
            dato("Colegio", pedido.school_name_snapshot or "Pedido independiente"),
            dato("Campaña", pedido.campaign_name_snapshot),
        ],
    ], colWidths=[ancho * 0.34, ancho * 0.38, ancho * 0.28])
    informacion.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))

    filas = [[
        _parrafo("N.º", encabezado),
        _parrafo("Código", encabezado),
        _parrafo("Producto / material educativo", encabezado),
        _parrafo("Cantidad", encabezado_derecha),
        _parrafo(f"Costo unit. ({moneda})", encabezado_derecha),
        _parrafo(f"Importe ({moneda})", encabezado_derecha),
    ]]
    total = Decimal("0.00")
    unidades = 0
    for indice, item in enumerate(detalles, start=1):
        importe = item.unit_supplier_cost * item.quantity_ordered
        total += importe
        unidades += item.quantity_ordered
        filas.append([
            _parrafo(indice, pequeno),
            _parrafo(item.product_code_snapshot or "—", pequeno),
            _parrafo(item.product_name_snapshot, principal),
            _parrafo(item.quantity_ordered, derecha),
            _parrafo(_importe(item.unit_supplier_cost), derecha),
            _parrafo(_importe(importe), derecha),
        ])
    anchos = [25, 98, ancho - 25 - 98 - 70 - 100 - 112, 70, 100, 112]
    tabla = LongTable(filas, colWidths=anchos, repeatRows=1, hAlign="LEFT")
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ROJO),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, CLARO]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, ROJO),
    ]))
    totales = Table([[
        _parrafo(f"Productos: {len(detalles)}   ·   Unidades: {unidades}", encabezado),
        _parrafo(f"TOTAL ORDEN ({moneda})", encabezado),
        _parrafo(_importe(total), encabezado_derecha),
    ]], colWidths=[ancho - 330, 190, 140])
    totales.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NEGRO),
        ("ALIGN", (2, 0), (2, 0), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    contenido = [
        cabecera, Spacer(1, 8), informacion, Spacer(1, 9),
        tabla, Spacer(1, 8), totales, Spacer(1, 7),
        _parrafo(
            "Documento para remisión manual a la editorial. La entrega y recepción de "
            "mercadería se registran por separado. Los importes reflejan los costos "
            "acordados en el pedido; esta orden no sustituye un comprobante tributario.",
            pequeno,
        ),
    ]

    def dibujar_pie(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(BORDE)
        canvas.line(margen, 12 * mm, ancho_pagina - margen, 12 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(GRIS)
        canvas.drawString(margen, 8 * mm, f"Book Express · Orden {numero}")
        canvas.drawRightString(ancho_pagina - margen, 8 * mm, f"Página {doc.page}")
        canvas.restoreState()

    documento.build(contenido, onFirstPage=dibujar_pie, onLaterPages=dibujar_pie)
    return buffer.getvalue()
