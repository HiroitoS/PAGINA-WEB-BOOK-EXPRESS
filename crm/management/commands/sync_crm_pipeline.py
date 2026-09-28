from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

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
        "name": "Cita",
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

LEGACY_ORDER_BY_CODE = {
    "proyeccion_ventas": 10,
    "cita_presentacion": 20,
    "decisor_influenciador": 30,
    "cotizacion_enviada": 40,
    "cierre_ganado_adopcion": 50,
    "cierre_perdido": 60,
}


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

        pipeline.stages.filter(is_initial=True).update(is_initial=False)

        existing_stages = list(
            pipeline.stages.all().order_by("id")
        )
        existing_by_code = {
            stage.code: stage
            for stage in existing_stages
        }
        existing_by_legacy_order = {
            stage.order: stage
            for stage in existing_stages
        }

        used_orders = {
            stage.order
            for stage in existing_stages
        }
        temporary_order = 10000

        for stage in existing_stages:
            while temporary_order in used_orders:
                temporary_order += 1

            stage.order = temporary_order
            stage.save(
                update_fields=[
                    "order",
                    "updated_at",
                ]
            )
            used_orders.add(temporary_order)
            temporary_order += 1

        used_stage_ids = set()
        canonical_by_code = {}

        for stage_data in DEFAULT_STAGES:
            stage = existing_by_code.get(stage_data["code"])

            if stage is None:
                legacy_order = LEGACY_ORDER_BY_CODE.get(
                    stage_data["code"]
                )
                legacy_stage = (
                    existing_by_legacy_order.get(legacy_order)
                    if legacy_order is not None
                    else None
                )

                if (
                    legacy_stage is not None
                    and legacy_stage.code != "cotizacion_aceptada"
                    and legacy_stage.pk not in used_stage_ids
                ):
                    stage = legacy_stage

            if stage is None:
                stage = PipelineStage(
                    pipeline=pipeline,
                )

            stage.code = stage_data["code"]
            stage.name = stage_data["name"]
            stage.order = stage_data["order"]
            stage.category = stage_data["category"]
            stage.is_initial = stage_data["is_initial"]
            stage.is_active = True
            stage.full_clean()
            stage.save()

            used_stage_ids.add(stage.pk)
            canonical_by_code[stage.code] = stage

        quotation_stage = canonical_by_code["cotizacion_enviada"]
        accepted_stage = existing_by_code.get("cotizacion_aceptada")

        if (
            accepted_stage is not None
            and accepted_stage.pk not in used_stage_ids
        ):
            pipeline.opportunities.filter(
                stage=accepted_stage,
            ).update(
                stage=quotation_stage,
                updated_at=timezone.now(),
            )

        for stage in existing_stages:
            if stage.pk in used_stage_ids:
                continue

            stage.is_initial = False
            stage.is_active = False
            stage.save(
                update_fields=[
                    "is_initial",
                    "is_active",
                    "updated_at",
                ]
            )

        action = "creado" if created else "actualizado"
        self.stdout.write(
            self.style.SUCCESS(
                f"Pipeline comercial {action} correctamente."
            )
        )
