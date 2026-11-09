"""Prepara una demostración segura sin inventar ventas ni firmas.

Uso:
  python manage.py preparar_demo_erp --year 2027
  python manage.py preparar_demo_erp --year 2027 --crear --local
  DB_NAME=bookexpress_demo_db python manage.py preparar_demo_erp --year 2027 --crear

La vista previa es de solo lectura. --crear --local solo funciona en PostgreSQL
local bookexpress_db con DEBUG=True. El modo de base aislada se mantiene.
Crea una oportunidad, proyección y cotización en BORRADOR usando la campaña
escolar activa, nunca otra campaña ni una adopción o recepción confirmada.
"""
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.models import Product, ProductPrice
from crm.models import (
    Campaign, CommercialQuotation, Pipeline,
    School, SchoolContact, SchoolEducationalService,
)
from crm.services import (
    create_commercial_projection_revision,
    create_commercial_quotation_from_projection,
    create_opportunity,
)
from crm.services.education import grade_matches_level


DEMO_PREFIX = "[PRUEBA ERP]"


def _is_local_connection():
    config = settings.DATABASES["default"]
    return (
        settings.DEBUG
        and config.get("ENGINE") == "django.db.backends.postgresql"
        and str(config.get("HOST") or "").lower() in {"localhost", "127.0.0.1", "::1"}
    )


def _is_demo_database():
    config = settings.DATABASES["default"]
    name = str(config.get("NAME") or "").lower()
    return _is_local_connection() and name.startswith("bookexpress_demo_")


def _is_local_dev_database():
    config = settings.DATABASES["default"]
    return _is_local_connection() and str(config.get("NAME") or "").lower() == "bookexpress_db"


def _eligible_products(year, selected_id=None):
    query = Product.objects.filter(
        is_active=True,
        level__is_active=True,
        grade__is_active=True,
        commercial_line=Product.CommercialLine.SCHOOL_TEXT,
        prices__year=year,
        prices__is_active=True,
        prices__price__gt=0,
    ).select_related("provider", "level", "grade").distinct().order_by("pk")
    if selected_id:
        query = query.filter(pk=selected_id)
    return [product for product in query if grade_matches_level(
        grade=product.grade, level=product.level,
    )]


def _eligible_schools(selected_id=None):
    query = School.objects.filter(is_active=True).exclude(
        name__startswith=DEMO_PREFIX,
    ).order_by("pk")
    if selected_id:
        query = query.filter(pk=selected_id)
    return query


class Command(BaseCommand):
    help = (
        "Consulta colegios y libros importados; opcionalmente prepara un "
        "escenario de prueba aislado hasta cotización en borrador."
    )

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, default=2027)
        parser.add_argument("--school-id", type=int)
        parser.add_argument("--product-id", type=int)
        parser.add_argument("--quantity", type=int, default=10)
        parser.add_argument(
            "--crear", action="store_true",
            help="Registra una prueba delimitada; necesita base demo o --local.",
        )
        parser.add_argument(
            "--local", action="store_true",
            help="Autoriza pruebas claramente identificadas solo en bookexpress_db local.",
        )

    def handle(self, *args, **options):
        year = options["year"]
        quantity = options["quantity"]
        if not 2020 <= year <= 2100:
            raise CommandError("Selecciona un año válido (2020–2100).")
        if not 1 <= quantity <= 10000:
            raise CommandError("La cantidad de prueba debe estar entre 1 y 10 000.")

        # Nunca adivinamos que una firma o una venta sea real. Escogemos
        # datos maestros importados, pero creamos un colegio claramente DEMO.
        school_qs = _eligible_schools(options["school_id"])
        school = school_qs.first()
        products = _eligible_products(year, options["product_id"])
        product = products[0] if products else None
        total_schools = _eligible_schools().count()
        total_products = Product.objects.filter(is_active=True).count()
        priced = ProductPrice.objects.filter(
            year=year, is_active=True, price__gt=0,
        ).values("product_id").distinct().count()

        self.stdout.write(f"Base: {settings.DATABASES['default']['NAME']}")
        self.stdout.write(f"Colegios activos cargados: {total_schools}")
        self.stdout.write(f"Productos activos cargados: {total_products}")
        self.stdout.write(f"Productos con PVP numérico en {year}: {priced}")
        self.stdout.write(
            "Nota: la importación de colegios y productos NO crea "
            "cotizaciones, adopciones, pedidos ni existencias."
        )
        if school:
            self.stdout.write(f"Colegio de referencia: #{school.pk} {school.name}")
        if product:
            self.stdout.write(
                f"Libro de referencia: #{product.pk} {product.name} "
                f"· {product.provider.name} · "
                f"{product.level.name} / {product.grade.name}"
            )

        if school is None:
            raise CommandError(
                "No hay colegios activos compatibles. Verifica la importación "
                "o el ID seleccionado."
            )
        if product is None:
            raise CommandError(
                f"No hay textos escolares activos con nivel, grado y precio "
                f"numérico de {year}. Revisa clasificaciones y precios del catálogo."
            )

        pipeline = Pipeline.objects.filter(
            is_default=True, is_active=True,
        ).first()
        if not pipeline or not pipeline.stages.filter(
            is_initial=True, is_active=True,
        ).exists():
            raise CommandError(
                "Falta configurar el pipeline comercial predeterminado "
                "y su etapa inicial. Revisa Configuración de CRM."
            )

        campaigns = list(Campaign.objects.filter(
            year=year,
            campaign_type=Campaign.CampaignType.SCHOOL,
            status=Campaign.Status.ACTIVE,
        ).order_by("pk")[:2])
        if len(campaigns) != 1:
            raise CommandError(
                f"Debe existir exactamente una campaña escolar activa para {year}. "
                "Revísala en CRM → Campañas; no se creará otra campaña."
            )
        campaign = campaigns[0]

        self.stdout.write(f"Campaña activa que se reutilizará: {campaign.name}")
        self.stdout.write(
            "Recorrido propuesto: colegio DEMO → oportunidad → proyección "
            "→ cotización en BORRADOR → revisión manual en CRM → "
            "aceptación/adopción simulada → Compras → Almacén."
        )
        if not options["crear"]:
            self.stdout.write(self.style.SUCCESS(
                "Vista previa terminada. No se cambió ningún registro. "
                "Para crear un escenario de prueba en tu PostgreSQL local "
                "usa --crear --local."
            ))
            return

        if options["local"] and not _is_local_dev_database():
            raise CommandError(
                "Operación bloqueada. --local solo está disponible en "
                "bookexpress_db con PostgreSQL local y DEBUG=True. "
                "No ejecutes datos de demostración en producción."
            )
        if not (_is_demo_database() or (options["local"] and _is_local_dev_database())):
            raise CommandError(
                "Operación bloqueada. Para preparar datos en tu base local "
                "de desarrollo ejecuta --crear --local. Nunca en producción."
            )

        User = get_user_model()
        actor = User.objects.filter(is_superuser=True, is_active=True).order_by("pk").first()
        if actor is None:
            raise CommandError(
                "No existe un superusuario activo para registrar el caso de prueba."
            )

        demo_code = f"DEMO{year}S{school.pk}"[:24]
        with transaction.atomic():
            existing = School.objects.filter(book_express_code=demo_code).first()
            if existing:
                opportunity = existing.opportunities.order_by("pk").first()
                self.stdout.write(self.style.WARNING(
                    f"Ya existe el escenario: colegio DEMO #{existing.pk}; "
                    f"oportunidad #{opportunity.pk if opportunity else 'sin crear'}. "
                    "No se generó una copia."
                ))
                return

            demo_school = School.objects.create(
                book_express_code=demo_code,
                name=f"{DEMO_PREFIX} Colegio de demostración {year}"[:220],
                notes=(
                    f"Escenario de prueba basado en el colegio de referencia #{school.pk}. "
                    "NO es una negociación ni adopción real."
                ),
                owner=actor,
                created_by=actor,
            )
            demo_school.levels.add(product.level)
            contact = SchoolContact.objects.create(
                school=demo_school,
                full_name=f"{DEMO_PREFIX} Contacto ficticio",
                position="Responsable de demostración",
                decision_role=SchoolContact.DecisionRole.DECISION_MAKER,
                is_primary=True,
                created_by=actor,
            )
            service = SchoolEducationalService.objects.create(
                school=demo_school,
                level=product.level,
                created_by=actor,
            )
            opportunity = create_opportunity(
                school=demo_school,
                campaign=campaign,
                pipeline=pipeline,
                created_by=actor,
                owner=actor,
                primary_contact=contact,
                title=f"{DEMO_PREFIX} Flujo de libros {year}",
                notes="Prueba controlada; no contactar al colegio de referencia.",
            )
            projection = create_commercial_projection_revision(
                opportunity=opportunity,
                actor=actor,
                commercial_line=Product.CommercialLine.SCHOOL_TEXT,
                grade_lines=[{
                    "service": service,
                    "grade": product.grade,
                    "section_count": 1,
                    "student_count": quantity,
                }],
                items=[{
                    "service": service,
                    "grade": product.grade,
                    "product": product,
                    "quantity": quantity,
                }],
                notes="Población simulada para verificar el flujo de preparación de libros.",
            )
            quotation = create_commercial_quotation_from_projection(
                opportunity=opportunity,
                actor=actor,
                sale_mode=CommercialQuotation.SaleMode.POINT_OF_SALE,
                service_date=max(date(year, 2, 15), date.today() + timedelta(days=7)),
                notes=(
                    "DEMOSTRACIÓN: cotización en borrador. Descuento editorial "
                    "y aceptación requieren revisión manual."
                ),
            )

        self.stdout.write(self.style.SUCCESS(
            f"Escenario creado: colegio #{demo_school.pk}, oportunidad "
            f"#{opportunity.pk}, proyección #{projection.pk} y cotización "
            f"#{quotation.pk} EN BORRADOR."
        ))
        self.stdout.write(
            "Abre el CRM de esta base local: completa la condición editorial, "
            "envía y acepta la cotización SOLO COMO PRUEBA, "
            "confirma la adopción ficticia y genera pedidos desde Compras. "
            "Después prueba recepciones parciales y traslados reales de DEMO."
        )
