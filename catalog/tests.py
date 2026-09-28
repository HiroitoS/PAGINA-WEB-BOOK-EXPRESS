import shutil
import tempfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from openpyxl import Workbook

from catalog.services.importar_productos_excel import (
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
