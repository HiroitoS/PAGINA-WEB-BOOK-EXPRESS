from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from catalog.models import (
    Area,
    Grade,
    Level,
    Product,
    ProductPrice,
    Provider,
)
from crm.models import (
    Campaign,
    CommercialProjection,
    CommercialTeam,
    CommercialTeamMembership,
    Opportunity,
    Pipeline,
    PipelineStage,
    School,
    SchoolEducationalService,
    SchoolPopulationDetail,
    SchoolPopulationRecord,
)
from crm.services import (
    CommercialProjectionError,
    create_commercial_projection_revision,
)


User = get_user_model()


def grant_permission(user, codename):
    permission = Permission.objects.get(
        content_type__app_label="crm",
        codename=codename,
    )
    user.user_permissions.add(permission)


class CRMCommercialProjectionTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.admin = User.objects.create_superuser(
            username="crm-projection-admin",
            email="projection-admin@example.com",
            password="test-password",
        )
        self.advisor = User.objects.create_user(
            username="crm-projection-advisor",
            password="test-password",
        )
        grant_permission(self.advisor, "view_crm")
        grant_permission(
            self.advisor,
            "manage_own_opportunities",
        )

        self.team = CommercialTeam.objects.create(
            code="CRM-PROJ-TEAM",
            name="Equipo proyección",
            created_by=self.admin,
        )
        CommercialTeamMembership.objects.create(
            team=self.team,
            user=self.advisor,
            role=CommercialTeamMembership.Role.ADVISOR,
            created_by=self.admin,
        )

        self.school = School.objects.create(
            name="Colegio Proyección",
            team=self.team,
            owner=self.advisor,
            created_by=self.admin,
        )

        self.level = Level.objects.create(
            name="Primaria Proyección",
            is_active=True,
        )
        self.grade = Grade.objects.create(
            name="4to Primaria Proyección",
            order=4,
            is_active=True,
        )
        self.other_grade = Grade.objects.create(
            name="5to Primaria Proyección",
            order=5,
            is_active=True,
        )
        self.area = Area.objects.create(
            name="Matemática Proyección",
            is_active=True,
        )

        self.service = SchoolEducationalService.objects.create(
            school=self.school,
            level=self.level,
            is_active=True,
            created_by=self.admin,
        )

        self.population = SchoolPopulationRecord.objects.create(
            service=self.service,
            year=2026,
            student_count=60,
            is_current=True,
            recorded_by=self.admin,
        )
        SchoolPopulationDetail.objects.create(
            population=self.population,
            grade=self.grade,
            section_count=2,
            students_per_section=30,
        )

        self.campaign = Campaign.objects.create(
            code="CRM-PROJ-2027",
            name="Campaña escolar 2027",
            year=2027,
            campaign_type=Campaign.CampaignType.SCHOOL,
            status=Campaign.Status.ACTIVE,
            created_by=self.admin,
        )

        self.pipeline = Pipeline.objects.create(
            code="CRM-PROJ-PIPE",
            name="Pipeline proyección",
            is_default=True,
            created_by=self.admin,
        )
        self.stage = PipelineStage.objects.create(
            pipeline=self.pipeline,
            code="proyeccion_ventas",
            name="Proyección de ventas",
            order=10,
            category=PipelineStage.Category.OPEN,
            is_initial=True,
            created_by=self.admin,
        )

        self.opportunity = Opportunity.objects.create(
            title="Campaña escolar 2027 - Colegio Proyección",
            school=self.school,
            campaign=self.campaign,
            pipeline=self.pipeline,
            stage=self.stage,
            team=self.team,
            owner=self.advisor,
            created_by=self.admin,
        )

        self.provider = Provider.objects.create(
            name="Editorial Proyección",
            is_active=True,
        )
        self.product = Product.objects.create(
            provider=self.provider,
            name="Matemática 4 Proyección",
            level=self.level,
            grade=self.grade,
            area=self.area,
            is_active=True,
        )
        ProductPrice.objects.create(
            product=self.product,
            year=2027,
            campaign="Campaña escolar",
            price=Decimal("50.00"),
            cost_price=Decimal("30.00"),
            is_active=True,
        )

    def _create_projection(self, **overrides):
        grade_lines = overrides.pop(
            "grade_lines",
            [
                {
                    "service": self.service,
                    "grade": self.grade,
                }
            ],
        )
        items = overrides.pop(
            "items",
            [
                {
                    "service": self.service,
                    "grade": self.grade,
                    "product": self.product,
                }
            ],
        )

        return create_commercial_projection_revision(
            opportunity=self.opportunity,
            actor=self.advisor,
            grade_lines=grade_lines,
            items=items,
            **overrides,
        )

    def test_projection_uses_current_population_and_campaign_price(self):
        projection = self._create_projection()

        grade_line = projection.grades.get()
        item = projection.items.get()

        self.assertEqual(projection.version, 1)
        self.assertTrue(projection.is_current)
        self.assertEqual(grade_line.section_count, 2)
        self.assertEqual(grade_line.student_count, 60)
        self.assertEqual(item.quantity, 60)
        self.assertEqual(item.unit_price, Decimal("50.00"))
        self.assertEqual(item.subtotal, Decimal("3000.00"))
        self.assertEqual(
            item.price_campaign_snapshot,
            "Campaña escolar",
        )

    def test_projection_revision_preserves_previous_version(self):
        first = self._create_projection()

        second = self._create_projection(
            grade_lines=[
                {
                    "service": self.service,
                    "grade": self.grade,
                    "section_count": 2,
                    "student_count": 55,
                }
            ],
            items=[
                {
                    "service": self.service,
                    "grade": self.grade,
                    "product": self.product,
                    "quantity": 55,
                }
            ],
        )

        first.refresh_from_db()

        self.assertFalse(first.is_current)
        self.assertTrue(second.is_current)
        self.assertEqual(second.version, 2)
        self.assertEqual(
            CommercialProjection.objects.filter(
                opportunity=self.opportunity,
            ).count(),
            2,
        )

    def test_projection_rejects_product_from_another_grade(self):
        wrong_product = Product.objects.create(
            provider=self.provider,
            name="Matemática 5 Proyección",
            level=self.level,
            grade=self.other_grade,
            area=self.area,
            is_active=True,
        )
        ProductPrice.objects.create(
            product=wrong_product,
            year=2027,
            campaign="Campaña escolar",
            price=Decimal("55.00"),
            is_active=True,
        )

        with self.assertRaisesMessage(
            CommercialProjectionError,
            "no corresponde al grado",
        ):
            self._create_projection(
                items=[
                    {
                        "service": self.service,
                        "grade": self.grade,
                        "product": wrong_product,
                    }
                ],
            )

    def test_projection_rejects_product_without_campaign_price(self):
        product_without_price = Product.objects.create(
            provider=self.provider,
            name="Producto sin precio Proyección",
            level=self.level,
            grade=self.grade,
            area=self.area,
            is_active=True,
        )

        with self.assertRaisesMessage(
            CommercialProjectionError,
            "no tiene precio activo",
        ):
            self._create_projection(
                items=[
                    {
                        "service": self.service,
                        "grade": self.grade,
                        "product": product_without_price,
                    }
                ],
            )

    def test_projection_api_creates_reads_and_exposes_base_population(self):
        self.client.force_authenticate(user=self.advisor)

        base_response = self.client.get(
            reverse(
                "crm:opportunity-projection-base",
                args=[self.opportunity.id],
            )
        )

        self.assertEqual(base_response.status_code, 200)
        self.assertEqual(
            base_response.data["campaign"]["year"],
            2027,
        )
        self.assertEqual(
            base_response.data["services"][0][
                "latest_population"
            ]["details"][0]["student_count"],
            60,
        )

        create_response = self.client.post(
            reverse(
                "crm:opportunity-projection",
                args=[self.opportunity.id],
            ),
            {
                "grades": [
                    {
                        "service": self.service.id,
                        "grade": self.grade.id,
                    }
                ],
                "items": [
                    {
                        "service": self.service.id,
                        "grade": self.grade.id,
                        "product": self.product.id,
                    }
                ],
                "notes": "Proyección inicial",
            },
            format="json",
        )

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(create_response.data["version"], 1)
        self.assertEqual(
            create_response.data["total_students"],
            60,
        )
        self.assertEqual(
            create_response.data["total_amount"],
            "3000.00",
        )
        self.assertEqual(
            create_response.data["editorial_totals"][0],
            {
                "editorial": "Editorial Proyección",
                "amount": "3000.00",
            },
        )

        get_response = self.client.get(
            reverse(
                "crm:opportunity-projection",
                args=[self.opportunity.id],
            )
        )

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.data["version"], 1)

        history_response = self.client.get(
            reverse(
                "crm:opportunity-projection-history",
                args=[self.opportunity.id],
            )
        )

        self.assertEqual(history_response.status_code, 200)
        self.assertEqual(len(history_response.data), 1)
