from django.core.management import call_command
from django.test import TestCase

from crm.management.commands.sync_crm_pipeline import (
    DEFAULT_STAGES,
    PIPELINE_CODE,
)
from crm.models import Campaign, Pipeline, PipelineStage, School


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

    def test_sync_deactivates_accidental_accepted_stage_and_recovers_opportunity(self):
        pipeline = Pipeline.objects.create(
            code=PIPELINE_CODE,
            name="Pipeline con etapa accidental",
            is_active=True,
        )

        stage_specs = [
            ("proyeccion_ventas", "Proyección de ventas", 10, PipelineStage.Category.OPEN, True),
            ("cita_presentacion", "Cita / presentación", 20, PipelineStage.Category.OPEN, False),
            ("decisor_influenciador", "Decisor e influenciador", 30, PipelineStage.Category.OPEN, False),
            ("cotizacion_enviada", "Cotización enviada", 40, PipelineStage.Category.OPEN, False),
            ("cotizacion_aceptada", "Cotización aceptada / pendiente de adopción", 50, PipelineStage.Category.OPEN, False),
            ("cierre_ganado_adopcion", "Cierre ganado (adopción)", 60, PipelineStage.Category.WON, False),
            ("cierre_perdido", "Cierre perdido", 70, PipelineStage.Category.LOST, False),
        ]

        stages = {}
        for code, name, order, category, is_initial in stage_specs:
            stages[code] = PipelineStage.objects.create(
                pipeline=pipeline,
                code=code,
                name=name,
                order=order,
                category=category,
                is_initial=is_initial,
                is_active=True,
            )

        school = School.objects.create(name="Colegio Pipeline")
        campaign = Campaign.objects.create(
            code="PIPE-2027",
            name="Campaña 2027",
            year=2027,
            campaign_type=Campaign.CampaignType.SCHOOL,
            status=Campaign.Status.ACTIVE,
        )
        opportunity = school.opportunities.create(
            title="Oportunidad Pipeline",
            campaign=campaign,
            pipeline=pipeline,
            stage=stages["cotizacion_aceptada"],
        )

        won_id = stages["cierre_ganado_adopcion"].id
        lost_id = stages["cierre_perdido"].id

        call_command("sync_crm_pipeline")

        opportunity.refresh_from_db()
        stages["cotizacion_aceptada"].refresh_from_db()

        active_stages = pipeline.stages.filter(is_active=True).order_by("order")

        self.assertEqual(active_stages.count(), 6)
        self.assertFalse(stages["cotizacion_aceptada"].is_active)
        self.assertEqual(
            opportunity.stage.code,
            "cotizacion_enviada",
        )
        self.assertEqual(
            pipeline.stages.get(code="cierre_ganado_adopcion").id,
            won_id,
        )
        self.assertEqual(
            pipeline.stages.get(code="cierre_ganado_adopcion").order,
            50,
        )
        self.assertEqual(
            pipeline.stages.get(code="cierre_perdido").id,
            lost_id,
        )
        self.assertEqual(
            pipeline.stages.get(code="cierre_perdido").order,
            60,
        )
        self.assertEqual(
            pipeline.stages.get(code="cita_presentacion").name,
            "Cita",
        )

