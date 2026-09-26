from django.core.management.base import BaseCommand
from django.db import transaction

from crm.models import Pipeline, PipelineStage


PIPELINE_CODE = "BOOK-EXPRESS-COMMERCIAL"

DEFAULT_STAGES = [
    {
        "code": "proyeccion_ventas",
        "name": "Proyección de ventas",
        "order": 10,
        "category": PipelineStage.Category.OPEN,
        "is_initial": True,
    },
    {
        "code": "cita_presentacion",
        "name": "Cita / presentación",
        "order": 20,
        "category": PipelineStage.Category.OPEN,
        "is_initial": False,
    },
    {
        "code": "decisor_influenciador",
        "name": "Decisor e influenciador",
        "order": 30,
        "category": PipelineStage.Category.OPEN,
        "is_initial": False,
    },
    {
        "code": "cotizacion_enviada",
        "name": "Cotización enviada",
        "order": 40,
        "category": PipelineStage.Category.OPEN,
        "is_initial": False,
    },
    {
        "code": "cierre_ganado_adopcion",
        "name": "Cierre ganado (adopción)",
        "order": 50,
        "category": PipelineStage.Category.WON,
        "is_initial": False,
    },
    {
        "code": "cierre_perdido",
        "name": "Cierre perdido",
        "order": 60,
        "category": PipelineStage.Category.LOST,
        "is_initial": False,
    },
]


class Command(BaseCommand):
    help = "Crea o sincroniza el pipeline comercial base de Book Express."

    @transaction.atomic
    def handle(self, *args, **options):
        pipeline, created = Pipeline.objects.get_or_create(
            code=PIPELINE_CODE,
            defaults={
                "name": "Pipeline comercial Book Express",
                "description": (
                    "Seguimiento de oportunidades comerciales por colegio "
                    "y campaña, desde la proyección hasta el cierre."
                ),
                "is_active": True,
                "is_default": False,
            },
        )

        # Evita violar la restricción de un único pipeline predeterminado.
        Pipeline.objects.exclude(pk=pipeline.pk).filter(
            is_default=True
        ).update(is_default=False)

        pipeline.name = "Pipeline comercial Book Express"
        pipeline.description = (
            "Seguimiento de oportunidades comerciales por colegio "
            "y campaña, desde la proyección hasta el cierre."
        )
        pipeline.is_active = True
        pipeline.is_default = True
        pipeline.save(
            update_fields=[
                "name",
                "description",
                "is_active",
                "is_default",
                "updated_at",
            ]
        )

        # Liberamos primero la marca inicial para no chocar con la
        # restricción única mientras se sincroniza la configuración.
        pipeline.stages.filter(is_initial=True).update(is_initial=False)

        # La configuración anterior ya utilizaba seis posiciones
        # 10, 20, 30, 40, 50 y 60. Reutilizar la etapa existente por
        # posición conserva sus PK y, por tanto, cualquier relación o
        # historial ya registrado. Así evitamos duplicar etapas.
        existing_by_order = {
            stage.order: stage
            for stage in pipeline.stages.all()
        }

        for stage_data in DEFAULT_STAGES:
            stage = existing_by_order.get(stage_data["order"])

            if stage is None:
                stage = PipelineStage(
                    pipeline=pipeline,
                    order=stage_data["order"],
                )

            stage.code = stage_data["code"]
            stage.name = stage_data["name"]
            stage.category = stage_data["category"]
            stage.is_initial = stage_data["is_initial"]
            stage.is_active = True
            stage.full_clean()
            stage.save()

        action = "creado" if created else "actualizado"
        self.stdout.write(
            self.style.SUCCESS(
                f"Pipeline comercial {action} correctamente."
            )
        )
