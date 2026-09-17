from django.core.management.base import BaseCommand
from django.db import transaction

from crm.models import Pipeline, PipelineStage


PIPELINE_CODE = "BOOK-EXPRESS-COMMERCIAL"

DEFAULT_STAGES = [
    {
        "code": "por_contactar",
        "name": "Por contactar",
        "order": 10,
        "category": PipelineStage.Category.OPEN,
        "is_initial": True,
    },
    {
        "code": "contactado",
        "name": "Contactado",
        "order": 20,
        "category": PipelineStage.Category.OPEN,
        "is_initial": False,
    },
    {
        "code": "evaluacion",
        "name": "En evaluación",
        "order": 30,
        "category": PipelineStage.Category.OPEN,
        "is_initial": False,
    },
    {
        "code": "propuesta_negociacion",
        "name": "Propuesta / negociación",
        "order": 40,
        "category": PipelineStage.Category.OPEN,
        "is_initial": False,
    },
    {
        "code": "adopcion_confirmada",
        "name": "Adopción confirmada",
        "order": 50,
        "category": PipelineStage.Category.WON,
        "is_initial": False,
    },
    {
        "code": "no_concretada",
        "name": "No concretada",
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
                "name": "Proceso comercial Book Express",
                "description": (
                    "Pipeline base para el seguimiento de oportunidades "
                    "comerciales de colegios."
                ),
                "is_active": True,
                "is_default": False,
            },
        )

        # Evita violar la restricción de un único pipeline predeterminado.
        Pipeline.objects.exclude(pk=pipeline.pk).filter(
            is_default=True
        ).update(is_default=False)

        pipeline.name = "Proceso comercial Book Express"
        pipeline.description = (
            "Pipeline base para el seguimiento de oportunidades "
            "comerciales de colegios."
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

        # Primero liberamos la marca de etapa inicial para que una futura
        # reconfiguración del pipeline no choque con la restricción única.
        pipeline.stages.filter(is_initial=True).update(is_initial=False)

        for stage_data in DEFAULT_STAGES:
            PipelineStage.objects.update_or_create(
                pipeline=pipeline,
                code=stage_data["code"],
                defaults={
                    "name": stage_data["name"],
                    "order": stage_data["order"],
                    "category": stage_data["category"],
                    "is_initial": stage_data["is_initial"],
                    "is_active": True,
                },
            )

        action = "creado" if created else "actualizado"
        self.stdout.write(
            self.style.SUCCESS(
                f"Pipeline comercial {action} correctamente."
            )
        )
