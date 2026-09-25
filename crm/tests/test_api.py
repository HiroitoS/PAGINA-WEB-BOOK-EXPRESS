from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework.test import APIClient

from catalog.models import Area, Grade, Level, Provider
from crm.models import (
    Campaign,
    CommercialTeam,
    CommercialTeamMembership,
    CRMWorkItemLink,
    Opportunity,
    Pipeline,
    PipelineStage,
    School,
    SchoolContact,
    SchoolEducationalService,
    SchoolPopulationRecord,
    SchoolPopulationDetail,
    MarketEditorial,
)


User = get_user_model()


def grant_permission(user, codename):
    permission = Permission.objects.get(content_type__app_label="crm", codename=codename)
    user.user_permissions.add(permission)


class CRMApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(username="crm-api-admin", email="admin@example.com", password="test-password")
        self.supervisor = User.objects.create_user(username="crm-api-supervisor", password="test-password")
        self.advisor = User.objects.create_user(username="crm-api-advisor", password="test-password")
        self.other_advisor = User.objects.create_user(username="crm-api-other", password="test-password")
        self.no_access = User.objects.create_user(username="crm-api-no-access", password="test-password")
        for user in (self.supervisor, self.advisor, self.other_advisor):
            grant_permission(user, "view_crm")
            grant_permission(user, "manage_schools")
            grant_permission(user, "manage_own_opportunities")
        grant_permission(self.supervisor, "supervise_crm")
        grant_permission(self.supervisor, "assign_schools")
        grant_permission(self.supervisor, "assign_opportunities")

        self.team = CommercialTeam.objects.create(code="API-TEAM", name="Equipo API", created_by=self.admin)
        self.other_team = CommercialTeam.objects.create(code="API-OTHER", name="Otro equipo API", created_by=self.admin)
        CommercialTeamMembership.objects.create(team=self.team, user=self.supervisor, role=CommercialTeamMembership.Role.SUPERVISOR, created_by=self.admin)
        CommercialTeamMembership.objects.create(team=self.team, user=self.advisor, role=CommercialTeamMembership.Role.ADVISOR, created_by=self.admin)
        CommercialTeamMembership.objects.create(team=self.other_team, user=self.other_advisor, role=CommercialTeamMembership.Role.ADVISOR, created_by=self.admin)

        self.school = School.objects.create(name="Colegio API", team=self.team, owner=self.advisor, created_by=self.admin)
        self.other_school = School.objects.create(name="Otro Colegio API", team=self.other_team, owner=self.other_advisor, created_by=self.admin)
        self.campaign = Campaign.objects.create(code="API-2027", name="Campaña API 2027", year=2027, status=Campaign.Status.ACTIVE, created_by=self.admin)
        self.pipeline = Pipeline.objects.create(code="API-PIPE", name="Pipeline API", is_default=True, created_by=self.admin)
        self.initial_stage = PipelineStage.objects.create(pipeline=self.pipeline, code="por_contactar", name="Por contactar", order=10, category=PipelineStage.Category.OPEN, is_initial=True, created_by=self.admin)
        self.follow_up_stage = PipelineStage.objects.create(pipeline=self.pipeline, code="seguimiento", name="Seguimiento", order=20, category=PipelineStage.Category.OPEN, created_by=self.admin)
        self.lost_stage = PipelineStage.objects.create(pipeline=self.pipeline, code="no_concretada", name="No concretada", order=90, category=PipelineStage.Category.LOST, created_by=self.admin)
        self.opportunity = Opportunity.objects.create(title="Oportunidad API", school=self.school, campaign=self.campaign, pipeline=self.pipeline, stage=self.initial_stage, team=self.team, owner=self.advisor, created_by=self.admin)
        self.other_opportunity = Opportunity.objects.create(title="Otra oportunidad API", school=self.other_school, campaign=self.campaign, pipeline=self.pipeline, stage=self.initial_stage, team=self.other_team, owner=self.other_advisor, created_by=self.admin)

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def test_user_without_crm_permission_is_denied(self):
        self.authenticate(self.no_access)
        self.assertEqual(self.client.get(reverse("crm:school-list")).status_code, 403)

    def test_advisor_only_lists_own_scope(self):
        self.authenticate(self.advisor)
        response = self.client.get(reverse("crm:school-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.school.id)
        response = self.client.get(reverse("crm:opportunity-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.opportunity.id)

    def test_supervisor_sees_supervised_team_only(self):
        self.authenticate(self.supervisor)
        response = self.client.get(reverse("crm:opportunity-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["id"] for item in response.data["results"]}, {self.opportunity.id})

    def test_summary_respects_visible_scope(self):
        self.authenticate(self.advisor)
        response = self.client.get(reverse("crm:summary"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["schools"], 1)
        self.assertEqual(response.data["open_opportunities"], 1)

    def test_advisor_can_register_commercial_activity(self):
        self.authenticate(self.advisor)
        response = self.client.post(
            reverse("crm:opportunity-activities", args=[self.opportunity.id]),
            {"activity_type": "call", "summary": "Llamada a dirección", "result": "Solicitaron nueva visita."},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.opportunity.refresh_from_db()
        self.assertIsNotNone(self.opportunity.last_activity_at)

    def test_advisor_can_register_activity_directly_from_school_contact(self):
        contact = SchoolContact.objects.create(
            school=self.school,
            full_name="Directora contacto CRM",
            position="Directora",
            created_by=self.admin,
        )

        self.authenticate(self.advisor)

        response = self.client.post(
            reverse(
                "crm:school-activities",
                args=[self.school.id],
            ),
            {
                "activity_type": "visit",
                "summary": "Visita al colegio",
                "result": "Solicitaron propuesta académica.",
                "contact": contact.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["school_id"], self.school.id)
        self.assertIsNone(response.data["opportunity_id"])
        self.assertEqual(response.data["contact"]["id"], contact.id)

    def test_advisor_can_create_school_task_linked_to_contact_without_opportunity(
        self,
    ):
        contact = SchoolContact.objects.create(
            school=self.school,
            full_name="Coordinadora seguimiento CRM",
            position="Coordinadora",
            created_by=self.admin,
        )

        self.authenticate(self.advisor)

        response = self.client.post(
            reverse(
                "crm:school-create-task",
                args=[self.school.id],
            ),
            {
                "title": "Llamar a coordinadora",
                "contact": contact.id,
                "due_at": (
                    timezone.now() + timedelta(days=1)
                ).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            CRMWorkItemLink.objects.filter(
                school=self.school,
                contact=contact,
                opportunity__isnull=True,
                task_id=response.data["id"],
            ).exists()
        )

    def test_school_work_items_expose_linked_task_context(self):
        contact = SchoolContact.objects.create(
            school=self.school,
            full_name="Director agenda CRM",
            position="Director",
            created_by=self.admin,
        )

        self.authenticate(self.advisor)

        task_response = self.client.post(
            reverse(
                "crm:school-create-task",
                args=[self.school.id],
            ),
            {
                "title": "Preparar material para visita",
                "contact": contact.id,
            },
            format="json",
        )

        self.assertEqual(task_response.status_code, 201)

        response = self.client.get(
            reverse(
                "crm:school-work-items",
                args=[self.school.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["contact_id"],
            contact.id,
        )
        self.assertEqual(
            response.data["results"][0]["type"],
            "task",
        )

    def test_advisor_can_create_opportunity_from_school_defaults(self):
        school = School.objects.create(
            name="Colegio creación automática",
            team=self.team,
            owner=self.advisor,
            created_by=self.admin,
        )
        contact = SchoolContact.objects.create(
            school=school,
            full_name="Directora creación automática",
            position="Directora",
            is_primary=True,
            created_by=self.admin,
        )

        self.authenticate(self.advisor)
        response = self.client.post(
            reverse("crm:opportunity-list"),
            {"school": school.id},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.data["title"],
            f"{self.campaign.name} - {school.name}",
        )
        self.assertEqual(response.data["campaign"]["id"], self.campaign.id)
        self.assertEqual(response.data["pipeline"]["id"], self.pipeline.id)
        self.assertEqual(
            response.data["primary_contact"]["id"],
            contact.id,
        )
        self.assertEqual(response.data["owner"]["id"], self.advisor.id)
        self.assertEqual(response.data["team"]["id"], self.team.id)

    def test_opportunity_api_rejects_open_duplicate(self):
        self.authenticate(self.advisor)
        response = self.client.post(
            reverse("crm:opportunity-list"),
            {"school": self.school.id},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "Ya existe una oportunidad abierta",
            str(response.data),
        )

    def test_advisor_can_move_own_opportunity_to_open_stage(self):
        self.authenticate(self.advisor)
        response = self.client.post(
            reverse("crm:opportunity-change-stage", args=[self.opportunity.id]),
            {"stage": self.follow_up_stage.id, "note": "Se realizó primer contacto."},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.stage_id, self.follow_up_stage.id)

    def test_lost_stage_requires_reason(self):
        self.authenticate(self.advisor)
        response = self.client.post(
            reverse("crm:opportunity-change-stage", args=[self.opportunity.id]),
            {"stage": self.lost_stage.id, "note": ""},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_advisor_can_create_task_linked_to_opportunity(self):
        self.authenticate(self.advisor)
        response = self.client.post(
            reverse("crm:opportunity-create-task", args=[self.opportunity.id]),
            {"title": "Preparar propuesta", "due_at": (timezone.now() + timedelta(days=1)).isoformat()},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(CRMWorkItemLink.objects.filter(opportunity=self.opportunity, task_id=response.data["id"]).exists())

    def test_school_detail_exposes_services_population_and_segment(self):
        level = Level.objects.create(
            name="Primaria CRM API",
            is_active=True,
        )
        service = SchoolEducationalService.objects.create(
            school=self.school,
            level=level,
            modular_code="1234567",
            modality="Educación Básica Regular",
            created_by=self.admin,
        )
        SchoolPopulationRecord.objects.create(
            service=service,
            year=2026,
            student_count=520,
            source="manual",
            is_current=True,
            recorded_by=self.admin,
        )

        self.authenticate(self.advisor)
        response = self.client.get(
            reverse("crm:school-detail", args=[self.school.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["current_population_total"], 520)
        self.assertEqual(response.data["segment"], "A")
        self.assertEqual(
            response.data["educational_services"][0]["modular_code"],
            "1234567",
        )
        self.assertEqual(
            response.data["educational_services"][0]["level"]["name"],
            "Primaria CRM API",
        )

    def test_school_delete_is_not_exposed(self):
        self.authenticate(self.admin)
        response = self.client.delete(reverse("crm:school-detail", args=[self.school.id]))
        self.assertEqual(response.status_code, 405)

    def test_advisor_can_create_school_educational_service(self):
        level = Level.objects.create(
            name="Primaria servicio CRM",
            is_active=True,
        )

        self.authenticate(self.advisor)

        response = self.client.post(
            reverse(
                "crm:school-educational-services",
                args=[self.school.id],
            ),
            {
                "level": level.id,
                "modular_code": "7654321",
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

        service = SchoolEducationalService.objects.get(
            school=self.school,
            level=level,
        )

        self.assertEqual(service.modular_code, "7654321")
        self.assertEqual(
            response.data["level"]["name"],
            "Primaria servicio CRM",
        )

    def test_school_cannot_repeat_educational_level(self):
        level = Level.objects.create(
            name="Secundaria servicio CRM",
            is_active=True,
        )

        SchoolEducationalService.objects.create(
            school=self.school,
            level=level,
            modular_code="1111111",
            created_by=self.admin,
        )

        self.authenticate(self.advisor)

        response = self.client.post(
            reverse(
                "crm:school-educational-services",
                args=[self.school.id],
            ),
            {
                "level": level.id,
                "modular_code": "2222222",
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            SchoolEducationalService.objects.filter(
                school=self.school,
                level=level,
            ).count(),
            1,
        )

    def test_advisor_can_register_school_population(self):
        level = Level.objects.create(
            name="Primaria población CRM",
            is_active=True,
        )

        service = SchoolEducationalService.objects.create(
            school=self.school,
            level=level,
            modular_code="3333333",
            created_by=self.admin,
        )

        self.authenticate(self.advisor)

        response = self.client.post(
            reverse(
                "crm:school-educational-service-population",
                args=[self.school.id, service.id],
            ),
            {
                "year": 2026,
                "student_count": 320,
                "source": "advisor",
                "source_detail": "Dato informado por el colegio",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

        population = SchoolPopulationRecord.objects.get(
            service=service,
        )

        self.assertEqual(population.student_count, 320)
        self.assertTrue(population.is_current)
        self.assertEqual(population.recorded_by, self.advisor)

    def test_advisor_can_register_population_breakdown_by_grade(self):
        level = Level.objects.create(
            name="Primaria detalle CRM",
            is_active=True,
        )
        first_grade = Grade.objects.create(
            name="1ro Primaria detalle CRM",
            order=1,
            is_active=True,
        )
        second_grade = Grade.objects.create(
            name="2do Primaria detalle CRM",
            order=2,
            is_active=True,
        )
        service = SchoolEducationalService.objects.create(
            school=self.school,
            level=level,
            modular_code="3377337",
            created_by=self.admin,
        )

        self.authenticate(self.advisor)

        response = self.client.post(
            reverse(
                "crm:school-educational-service-population",
                args=[self.school.id, service.id],
            ),
            {
                "year": 2026,
                "source": "advisor",
                "source_detail": "Detalle informado por el colegio",
                "details": [
                    {
                        "grade": first_grade.id,
                        "section_count": 3,
                        "students_per_section": 20,
                    },
                    {
                        "grade": second_grade.id,
                        "section_count": 2,
                        "students_per_section": 25,
                    },
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["student_count"], 110)
        self.assertEqual(len(response.data["details"]), 2)

        population = SchoolPopulationRecord.objects.get(
            service=service,
            is_current=True,
        )

        self.assertEqual(population.student_count, 110)
        self.assertEqual(
            SchoolPopulationDetail.objects.filter(
                population=population,
            ).count(),
            2,
        )


    def test_new_population_replaces_current_population(self):
        level = Level.objects.create(
            name="Secundaria población CRM",
            is_active=True,
        )

        service = SchoolEducationalService.objects.create(
            school=self.school,
            level=level,
            modular_code="4444444",
            created_by=self.admin,
        )

        previous = SchoolPopulationRecord.objects.create(
            service=service,
            year=2025,
            student_count=280,
            source="manual",
            is_current=True,
            recorded_by=self.admin,
        )

        self.authenticate(self.advisor)

        response = self.client.post(
            reverse(
                "crm:school-educational-service-population",
                args=[self.school.id, service.id],
            ),
            {
                "year": 2026,
                "student_count": 310,
                "source": "advisor",
                "source_detail": "Actualización de población",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

        previous.refresh_from_db()

        self.assertFalse(previous.is_current)

        current = SchoolPopulationRecord.objects.get(
            service=service,
            is_current=True,
        )

        self.assertEqual(current.year, 2026)
        self.assertEqual(current.student_count, 310)

        self.assertEqual(
            SchoolPopulationRecord.objects.filter(
                service=service,
            ).count(),
            2,
        )

    def test_school_population_total_sums_current_levels(self):
        primary = Level.objects.create(
            name="Primaria total CRM",
            is_active=True,
        )
        secondary = Level.objects.create(
            name="Secundaria total CRM",
            is_active=True,
        )

        primary_service = SchoolEducationalService.objects.create(
            school=self.school,
            level=primary,
            modular_code="5555555",
            created_by=self.admin,
        )

        secondary_service = SchoolEducationalService.objects.create(
            school=self.school,
            level=secondary,
            modular_code="6666666",
            created_by=self.admin,
        )

        SchoolPopulationRecord.objects.create(
            service=primary_service,
            year=2026,
            student_count=300,
            source="manual",
            is_current=True,
            recorded_by=self.admin,
        )

        SchoolPopulationRecord.objects.create(
            service=secondary_service,
            year=2026,
            student_count=220,
            source="manual",
            is_current=True,
            recorded_by=self.admin,
        )

        self.authenticate(self.admin)

        response = self.client.get(
            reverse(
                "crm:school-detail",
                args=[self.school.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["current_population_total"],
            520,
        )
        self.assertEqual(
            response.data["segment"],
            "A",
        )

    def test_advisor_can_create_primary_school_contact(self):
        self.authenticate(self.advisor)

        response = self.client.post(
            reverse(
                "crm:school-contacts",
                args=[self.school.id],
            ),
            {
                "full_name": "Director de prueba",
                "position": "Director",
                "phone": "999111222",
                "is_primary": True,
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

        contact = self.school.contacts.get(
            full_name="Director de prueba",
        )

        self.assertTrue(contact.is_primary)
        self.assertTrue(contact.is_active)
        self.assertEqual(
            contact.created_by,
            self.advisor,
        )


    def test_advisor_can_register_contact_decision_context(self):
        self.authenticate(self.advisor)

        response = self.client.post(
            reverse(
                "crm:school-contacts",
                args=[self.school.id],
            ),
            {
                "full_name": "Coordinadora académica",
                "position": "Coordinadora",
                "decision_role": "influencer",
                "relationship_level": 4,
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["decision_role"], "influencer")
        self.assertEqual(
            response.data["decision_role_display"],
            "Influenciador",
        )
        self.assertEqual(response.data["relationship_level"], 4)

        contact = self.school.contacts.get(
            full_name="Coordinadora académica",
        )
        self.assertEqual(
            contact.decision_role,
            SchoolContact.DecisionRole.INFLUENCER,
        )
        self.assertEqual(contact.relationship_level, 4)


    def test_new_primary_contact_replaces_previous_primary(self):
        previous = self.school.contacts.create(
            full_name="Director anterior",
            position="Director",
            is_primary=True,
            created_by=self.admin,
        )

        self.authenticate(self.advisor)

        response = self.client.post(
            reverse(
                "crm:school-contacts",
                args=[self.school.id],
            ),
            {
                "full_name": "Nueva directora",
                "position": "Directora",
                "is_primary": True,
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

        previous.refresh_from_db()

        self.assertFalse(previous.is_primary)

        new_contact = self.school.contacts.get(
            full_name="Nueva directora",
        )

        self.assertTrue(new_contact.is_primary)



    def test_advisor_can_deactivate_primary_school_contact(self):
        contact = self.school.contacts.create(
            full_name="Contacto temporal",
            position="Coordinador",
            is_primary=True,
            is_active=True,
            created_by=self.admin,
        )

        self.authenticate(self.advisor)

        response = self.client.patch(
            reverse(
                "crm:school-contact-detail",
                args=[
                    self.school.id,
                    contact.id,
                ],
            ),
            {
                "is_active": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        contact.refresh_from_db()

        self.assertFalse(contact.is_active)
        self.assertFalse(contact.is_primary)



    def test_advisor_global_contacts_only_list_own_scope(self):
        own_contact = SchoolContact.objects.create(
            school=self.school,
            full_name="Contacto visible CRM",
            position="Director",
            created_by=self.admin,
        )
        SchoolContact.objects.create(
            school=self.other_school,
            full_name="Contacto fuera de alcance CRM",
            position="Director",
            created_by=self.admin,
        )

        self.authenticate(self.advisor)

        response = self.client.get(
            reverse("crm:contact-list")
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["id"],
            own_contact.id,
        )
        self.assertEqual(
            response.data["results"][0]["school"]["id"],
            self.school.id,
        )

    def test_advisor_cannot_open_contact_outside_scope(self):
        other_contact = SchoolContact.objects.create(
            school=self.other_school,
            full_name="Contacto privado CRM",
            position="Director",
            created_by=self.admin,
        )

        self.authenticate(self.advisor)

        response = self.client.get(
            reverse(
                "crm:contact-detail",
                args=[other_contact.id],
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_global_contact_detail_exposes_related_school(self):
        contact = SchoolContact.objects.create(
            school=self.school,
            full_name="Directora ficha contacto CRM",
            position="Directora",
            created_by=self.admin,
        )

        self.authenticate(self.advisor)

        response = self.client.get(
            reverse(
                "crm:contact-detail",
                args=[contact.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], contact.id)
        self.assertEqual(
            response.data["school"]["id"],
            self.school.id,
        )
        self.assertEqual(
            response.data["school"]["name"],
            self.school.name,
        )

    def test_global_contact_update_preserves_single_primary_contact(self):
        previous = SchoolContact.objects.create(
            school=self.school,
            full_name="Director principal anterior CRM",
            position="Director",
            is_primary=True,
            created_by=self.admin,
        )
        contact = SchoolContact.objects.create(
            school=self.school,
            full_name="Nueva directora principal CRM",
            position="Directora",
            is_primary=False,
            created_by=self.admin,
        )

        self.authenticate(self.advisor)

        response = self.client.patch(
            reverse(
                "crm:contact-detail",
                args=[contact.id],
            ),
            {
                "is_primary": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        previous.refresh_from_db()
        contact.refresh_from_db()

        self.assertFalse(previous.is_primary)
        self.assertTrue(contact.is_primary)

    def test_global_contact_activities_only_show_selected_contact(self):
        contact = SchoolContact.objects.create(
            school=self.school,
            full_name="Directora actividades CRM",
            position="Directora",
            created_by=self.admin,
        )
        other_contact = SchoolContact.objects.create(
            school=self.school,
            full_name="Coordinadora actividades CRM",
            position="Coordinadora",
            created_by=self.admin,
        )

        self.authenticate(self.advisor)

        first_response = self.client.post(
            reverse(
                "crm:school-activities",
                args=[self.school.id],
            ),
            {
                "activity_type": "visit",
                "summary": "Visita con dirección",
                "result": "Solicitaron propuesta.",
                "contact": contact.id,
            },
            format="json",
        )
        second_response = self.client.post(
            reverse(
                "crm:school-activities",
                args=[self.school.id],
            ),
            {
                "activity_type": "call",
                "summary": "Llamada a coordinación",
                "result": "Pendiente nueva fecha.",
                "contact": other_contact.id,
            },
            format="json",
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 201)

        response = self.client.get(
            reverse(
                "crm:contact-activities",
                args=[contact.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["contact"]["id"],
            contact.id,
        )
        self.assertEqual(
            response.data["results"][0]["summary"],
            "Visita con dirección",
        )

    def test_global_contact_work_items_only_show_selected_contact(self):
        contact = SchoolContact.objects.create(
            school=self.school,
            full_name="Directora tareas CRM",
            position="Directora",
            created_by=self.admin,
        )
        other_contact = SchoolContact.objects.create(
            school=self.school,
            full_name="Coordinadora tareas CRM",
            position="Coordinadora",
            created_by=self.admin,
        )

        self.authenticate(self.advisor)

        first_response = self.client.post(
            reverse(
                "crm:school-create-task",
                args=[self.school.id],
            ),
            {
                "title": "Preparar reunión con dirección",
                "contact": contact.id,
            },
            format="json",
        )
        second_response = self.client.post(
            reverse(
                "crm:school-create-task",
                args=[self.school.id],
            ),
            {
                "title": "Llamar a coordinación",
                "contact": other_contact.id,
            },
            format="json",
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 201)

        response = self.client.get(
            reverse(
                "crm:contact-work-items",
                args=[contact.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["contact_id"],
            contact.id,
        )
        self.assertEqual(
            response.data["results"][0]["type"],
            "task",
        )
        self.assertEqual(
            response.data["results"][0]["item"]["title"],
            "Preparar reunión con dirección",
        )

    def test_global_contact_delete_is_not_exposed(self):
        contact = SchoolContact.objects.create(
            school=self.school,
            full_name="Contacto protegido CRM",
            position="Director",
            created_by=self.admin,
        )

        self.authenticate(self.admin)

        response = self.client.delete(
            reverse(
                "crm:contact-detail",
                args=[contact.id],
            )
        )

        self.assertEqual(response.status_code, 405)


    def test_advisor_can_register_school_editorial_usage(self):
        level = Level.objects.create(
            name="Primaria editorial CRM",
            is_active=True,
        )
        area = Area.objects.create(
            name="Matemática editorial CRM",
            is_active=True,
        )
        provider = Provider.objects.create(
            name="Editorial CRM",
            is_active=True,
        )
        editorial = MarketEditorial.objects.create(
            name="Editorial CRM",
            catalog_provider=provider,
            verification_status=(
                MarketEditorial.VerificationStatus.VERIFIED
            ),
            created_by=self.admin,
        )

        service = SchoolEducationalService.objects.create(
            school=self.school,
            level=level,
            modular_code="7777777",
            created_by=self.admin,
        )

        self.authenticate(self.advisor)

        response = self.client.post(
            reverse(
                "crm:school-editorial-usages",
                args=[self.school.id],
            ),
            {
                "year": 2026,
                "service": service.id,
                "area": area.id,
                "editorial": editorial.id,
                "status": "current",
                "source": "advisor",
                "notes": "Información confirmada.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            201,
        )

        usage = self.school.editorial_usages.get()

        self.assertEqual(
            usage.editorial,
            editorial,
        )
        self.assertEqual(
            usage.provider,
            provider,
        )
        self.assertEqual(
            usage.area,
            area,
        )
        self.assertEqual(
            usage.service,
            service,
        )
        self.assertEqual(
            usage.recorded_by,
            self.advisor,
        )

    def test_advisor_can_register_external_market_editorial(self):
        self.authenticate(self.advisor)

        response = self.client.post(
            reverse(
                "crm:market-editorial-list",
            ),
            {
                "name": "Editorial Centauro",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            201,
        )

        editorial = MarketEditorial.objects.get(
            name="Editorial Centauro",
        )

        self.assertIsNone(
            editorial.catalog_provider,
        )
        self.assertEqual(
            editorial.verification_status,
            MarketEditorial.VerificationStatus.PENDING,
        )
        self.assertEqual(
            editorial.created_by,
            self.advisor,
        )

    def test_advisor_can_register_external_editorial_usage(self):
        editorial = MarketEditorial.objects.create(
            name="Editorial Lobito",
            created_by=self.admin,
        )

        level = Level.objects.create(
            name="Primaria editorial externa CRM",
            is_active=True,
        )

        area = Area.objects.create(
            name="Comunicación editorial externa CRM",
            is_active=True,
        )

        service = SchoolEducationalService.objects.create(
            school=self.school,
            level=level,
            created_by=self.admin,
        )

        self.authenticate(self.advisor)

        response = self.client.post(
            reverse(
                "crm:school-editorial-usages",
                args=[self.school.id],
            ),
            {
                "year": 2026,
                "service": service.id,
                "area": area.id,
                "editorial": editorial.id,
                "status": "reported",
                "source": "advisor",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            201,
        )

        usage = self.school.editorial_usages.get()

        self.assertEqual(
            usage.editorial,
            editorial,
        )
        self.assertIsNone(
            usage.provider,
        )

    def test_school_editorial_usage_rejects_service_from_other_school(self):
        level = Level.objects.create(
            name="Secundaria editorial CRM",
            is_active=True,
        )

        editorial = MarketEditorial.objects.create(
            name="Editorial externa CRM",
            created_by=self.admin,
        )

        service = SchoolEducationalService.objects.create(
            school=self.other_school,
            level=level,
            modular_code="8888888",
            created_by=self.admin,
        )

        self.authenticate(self.advisor)

        response = self.client.post(
            reverse(
                "crm:school-editorial-usages",
                args=[self.school.id],
            ),
            {
                "year": 2026,
                "service": service.id,
                "editorial": editorial.id,
                "status": "reported",
                "source": "advisor",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            400,
        )



    def test_advisor_can_update_school_editorial_usage(self):
        provider = Provider.objects.create(
            name="Editorial actualización CRM",
            is_active=True,
        )

        editorial = MarketEditorial.objects.create(
            name="Editorial actualización CRM",
            catalog_provider=provider,
            verification_status=(
                MarketEditorial.VerificationStatus.VERIFIED
            ),
            created_by=self.admin,
        )

        usage = self.school.editorial_usages.create(
            year=2026,
            editorial=editorial,
            provider=provider,
            status="reported",
            source="manual",
            recorded_by=self.admin,
        )

        self.authenticate(self.advisor)

        response = self.client.patch(
            reverse(
                "crm:school-editorial-usage-detail",
                args=[
                    self.school.id,
                    usage.id,
                ],
            ),
            {
                "status": "current",
                "notes": "Información confirmada.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        usage.refresh_from_db()

        self.assertEqual(
            usage.status,
            "current",
        )
        self.assertEqual(
            usage.notes,
            "Información confirmada.",
        )
        self.assertEqual(
            usage.editorial,
            editorial,
        )
        self.assertEqual(
            usage.provider,
            provider,
        )

    def test_advisor_can_update_school_educational_service(self):
        level = Level.objects.create(
            name="Primaria edición CRM",
            is_active=True,
        )

        service = SchoolEducationalService.objects.create(
            school=self.school,
            level=level,
            modular_code="9990001",
            created_by=self.admin,
        )

        self.authenticate(self.advisor)

        response = self.client.patch(
            reverse(
                "crm:school-educational-service-detail",
                args=[
                    self.school.id,
                    service.id,
                ],
            ),
            {
                "modular_code": "9990002",
                "is_active": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        service.refresh_from_db()

        self.assertEqual(
            service.modular_code,
            "9990002",
        )
        self.assertFalse(service.is_active)