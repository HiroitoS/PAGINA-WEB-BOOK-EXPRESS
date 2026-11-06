import shutil
import tempfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from openpyxl import Workbook

from catalog.models import Product
from catalog.services.importar_productos_excel import (
    confirmar_importacion_productos,
    crear_vista_previa_productos,
)


class CatalogImportYearValidationTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.settings_override = override_settings(
            MEDIA_ROOT=self.media_root,
        )
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    def _build_catalog_file(self, row_year):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = f"Catalogo_Maestro_{row_year}"

        sheet.append(
            [
                "proveedor_editorial",
                "codigo_producto",
                "sku",
                "nombre",
                "tipo_producto",
                "anio_catalogo",
                "precio_costo",
                "precio_referencial",
                "consultar_precio",
                "disponibilidad",
                "activo",
            ]
        )
        sheet.append(
            [
                "Editorial Prueba",
                "COD-001",
                "",
                "Producto de prueba",
                "Texto escolar",
                row_year,
                50,
                80,
                "NO",
                "DISPONIBLE",
                "SI",
            ]
        )

        buffer = BytesIO()
        workbook.save(buffer)
        buffer.seek(0)

        return SimpleUploadedFile(
            f"catalogo_{row_year}.xlsx",
            buffer.read(),
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )

    def test_preview_rejects_row_year_different_from_selected_year(self):
        carga = crear_vista_previa_productos(
            archivo=self._build_catalog_file(2026),
            anio_catalogo=2027,
        )

        self.assertEqual(carga.estado, "ERROR")
        self.assertEqual(carga.total_errores, 1)

        detalle = carga.detalles.get()
        self.assertIn(
            "no coincide con el año seleccionado (2027)",
            " ".join(detalle.errores),
        )

    def test_preview_accepts_row_year_matching_selected_year(self):
        carga = crear_vista_previa_productos(
            archivo=self._build_catalog_file(2027),
            anio_catalogo=2027,
        )

        self.assertEqual(carga.estado, "VALIDADO")
        self.assertEqual(carga.total_errores, 0)

    def test_import_garden_access_with_sin_nivel_uses_generic_classification(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Catalogo_Maestro_2027"
        sheet.append([
            "proveedor_editorial",
            "codigo_producto",
            "nombre",
            "nivel",
            "grado",
            "serie",
            "tipo_producto",
            "linea_comercial",
            "anio_catalogo",
            "precio_referencial",
            "consultar_precio",
            "activo",
        ])
        sheet.append([
            "Santillana",
            "9900000030926",
            "CODIGO DE ACCESO AL SISTEMA GARDEN STAND ALONE",
            "Sin Nivel",
            "SIN NIVEL",
            "GARDEN",
            "Acceso digital",
            "Texto escolar",
            2027,
            9,
            "NO",
            "SI",
        ])

        buffer = BytesIO()
        workbook.save(buffer)
        archivo = SimpleUploadedFile(
            "garden_2027.xlsx",
            buffer.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )

        carga = crear_vista_previa_productos(
            archivo=archivo,
            anio_catalogo=2027,
        )
        self.assertEqual(carga.total_errores, 0)

        confirmar_importacion_productos(carga.pk)
        product = Product.objects.select_related("series").get(
            code="9900000030926",
        )
        self.assertIsNone(product.level_id)
        self.assertIsNone(product.grade_id)
        self.assertEqual(product.series.name, "GARDEN")
        self.assertEqual(product.commercial_line, Product.CommercialLine.SCHOOL_TEXT)
