"""Genera varios escenarios CRM de prueba a partir de colegios y libros importados.

Nunca modifica colegios reales, adopciones confirmadas, pedidos ni inventario.
Las escrituras pasan por preparar_demo_erp y servicios de negocio del CRM.

Uso:
  python manage.py preparar_demo_erp_lote --year 2027 --cantidad 3
  python manage.py preparar_demo_erp_lote --year 2027 --cantidad 3 --crear --local
"""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from crm.management.commands.preparar_demo_erp import (
    _eligible_products, _eligible_schools, _is_demo_database,
    _is_local_dev_database,
)


class Command(BaseCommand):
    help = "Prepara hasta cuatro escenarios de CRM en borrador, sin crear ventas ni stock."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, default=2027)
        parser.add_argument("--cantidad", type=int, default=3)
        parser.add_argument("--unidades", type=int, default=10)
        parser.add_argument("--crear", action="store_true")
        parser.add_argument("--local", action="store_true")

    def handle(self, *args, **options):
        year = options["year"]
        count = options["cantidad"]
        units = options["unidades"]
        if not 2020 <= year <= 2100:
            raise CommandError("Selecciona una campaña entre 2020 y 2100.")
        if not 1 <= count <= 4:
            raise CommandError("Por seguridad, puedes preparar entre uno y cuatro escenarios.")
        if not 1 <= units <= 10000:
            raise CommandError("Las unidades deben estar entre 1 y 10 000.")

        if options["crear"] and not (
            _is_demo_database()
            or (options["local"] and _is_local_dev_database())
        ):
            raise CommandError(
                "Operación bloqueada. Solo se pueden crear pruebas en "
                "bookexpress_db local con --crear --local o en la base demo aislada."
            )

        schools = list(_eligible_schools()[:count])
        eligible = _eligible_products(year)
        if len(schools) < count:
            raise CommandError(
                f"Se necesitan {count} colegios importados activos; solo hay {len(schools)}."
            )
        if not eligible:
            raise CommandError(
                f"No hay libros escolares activos con precios válidos para {year}."
            )

        # Preferimos editoriales distintas para probar abastecimientos independientes.
        first_by_provider = {}
        for product in eligible:
            first_by_provider.setdefault(product.provider_id, product)
        products = list(first_by_provider.values())
        products.extend(
            item for item in eligible
            if item.pk not in {p.pk for p in products}
        )
        selected = [
            (school, products[index % len(products)])
            for index, school in enumerate(schools)
        ]

        self.stdout.write("Se usarán colegios y productos ya importados, sin modificarlos:")
        for index, (school, product) in enumerate(selected, start=1):
            self.stdout.write(
                f"{index}. Colegio #{school.pk} {school.name} · "
                f"Libro #{product.pk} {product.name} · "
                f"Editorial {product.provider.name} · {units} unidades"
            )
        if not options["crear"]:
            self.stdout.write(self.style.SUCCESS(
                "Vista previa terminada. No se guardó ningún registro. "
                "Para crear borradores de prueba: --crear --local."
            ))
            return

        self.stdout.write(
            "Se crearán SOLO oportunidades, proyecciones y cotizaciones EN BORRADOR. "
            "Las adopciones y recepciones requieren confirmación desde el sistema."
        )
        # Se confirma el lote completo o no se guarda ninguno si hay error.
        with transaction.atomic():
            for school, product in selected:
                output = StringIO()
                call_command(
                    "preparar_demo_erp", year=year, school_id=school.pk,
                    product_id=product.pk, quantity=units,
                    crear=True, local=options["local"],
                    stdout=output,
                )
                lines = [
                    line.strip() for line in output.getvalue().splitlines()
                    if "Escenario creado:" in line or "Ya existe el escenario:" in line
                ]
                self.stdout.write(lines[-1] if lines else f"Revisar colegio #{school.pk}.")
        self.stdout.write(self.style.SUCCESS(
            "Escenarios listos para revisar en CRM. "
            "No se crearon pedidos, ventas ni existencias."
        ))
