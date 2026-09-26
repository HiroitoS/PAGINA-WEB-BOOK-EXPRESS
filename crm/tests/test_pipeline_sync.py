from django.core.management import call_command
from django.test import TestCase

from crm.management.commands.sync_crm_pipeline import (
    DEFAULT_STAGES,
    PIPELINE_CODE,
)
from crm.models import Pipeline, PipelineStage


class SyncCRMPipelineCommandTests(TestCase):
    def test_sync_creates_pipeline_with_approved_stages(self):
        call_command("sync_crm_pipeline")

        pipeline = Pipeline.objects.get(code=PIPELINE_CODE)
        stages = list(
            pipeline.stages.order_by("order").values(
                "code",
                "name",
                "order",
                "category",
                "is_initial",
                "is_active",
            )
        )

        self.assertEqual(len(stages), 6)
        self.assertTrue(pipeline.is_default)
        self.assertTrue(pipeline.is_active)

        expected = [
            {
                "code": item["code"],
                "name": item["name"],
                "order": item["order"],
                "category": item["category"],
                "is_initial": item["is_initial"],
                "is_active": True,
            }
            for item in DEFAULT_STAGES
        ]
        self.assertEqual(stages, expected)

    def test_sync_reuses_legacy_stage_ids_instead_of_duplicating(self):
        pipeline = Pipeline.objects.create(
            code=PIPELINE_CODE,
            name="Proceso comercial Book Express",
            is_active=True,
        )

        legacy_stages = [
            ("por_contactar", "Por contactar", 10, PipelineStage.Category.OPEN, True),
            ("contactado", "Contactado", 20, PipelineStage.Category.OPEN, False),
            ("evaluacion", "En evaluación", 30, PipelineStage.Category.OPEN, False),
            (
                "propuesta_negociacion",
                "Propuesta / negociación",
                40,
                PipelineStage.Category.OPEN,
                False,
            ),
            (
                "adopcion_confirmada",
                "Adopción confirmada",
                50,
                PipelineStage.Category.WON,
                False,
            ),
            (
                "no_concretada",
                "No concretada",
                60,
                PipelineStage.Category.LOST,
                False,
            ),
        ]

        original_ids = {}
        for code, name, order, category, is_initial in legacy_stages:
            stage = PipelineStage.objects.create(
                pipeline=pipeline,
                code=code,
                name=name,
                order=order,
                category=category,
                is_initial=is_initial,
                is_active=True,
            )
            original_ids[order] = stage.id

        call_command("sync_crm_pipeline")

        stages = pipeline.stages.order_by("order")
        self.assertEqual(stages.count(), 6)

        for expected in DEFAULT_STAGES:
            stage = stages.get(order=expected["order"])
            self.assertEqual(stage.id, original_ids[expected["order"]])
            self.assertEqual(stage.code, expected["code"])
            self.assertEqual(stage.name, expected["name"])
            self.assertEqual(stage.category, expected["category"])
            self.assertEqual(stage.is_initial, expected["is_initial"])
            self.assertTrue(stage.is_active)
