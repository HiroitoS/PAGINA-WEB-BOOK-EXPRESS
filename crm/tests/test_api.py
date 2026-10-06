from datetime import timedelta
import tempfile
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from rest_framework.test import APIClient

from catalog.models import Area, Grade, Level, Product, Provider
from crm.models import (
    Campaign,
    CommercialActivity,
    CommercialQuotation,
    CommercialTeam,
    CommercialTeamMembership,
    CRMHistoryEvent,
    CRMWorkItemLink,
    Opportunity,
    Pipeline,
    PipelineStage,
    School,
    SchoolCampus,
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
        self.quotation_stage = PipelineStage.objects.create(pipeline=self.pipeline, code="cotizacion_enviada", name="Cotización enviada", order=40, category=PipelineStage.Category.OPEN, created_by=self.admin)
        self.won_stage = PipelineStage.objects.create(pipeline=self.pipeline, code="cierre_ganado_adopcion", name="Cierre ganado (adopción)", order=80, category=PipelineStage.Category.WON, created_by=self.admin)
        self.lost_stage = PipelineStage.objects.create(pipeline=self.pipeline, code="no_concretada", name="No concretada", order=90, category=PipelineStage.Category.LOST, created_by=self.admin)
        self.opportunity = Opportunity.objects.create(title="Oportunidad API", school=self.school, campaign=self.campaign, pipeline=self.pipeline, stage=self.initial_stage, team=self.team, owner=self.advisor, created_by=self.admin)
        self.other_opportunity = Opportunity.objects.create(title="Otra oportunidad API", school=self.other_school, campaign=self.campaign, pipeline=self.pipeline, stage=self.initial_stage, team=self.other_team, owner=self.other_advisor, created_by=self.admin)

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def _create_quote_product(self):
        provider, _ = Provider.objects.get_or_create(
            name="Editorial cotización API",
            defaults={
                "is_active": True,
            },
        )
        level, _ = Level.objects.get_or_create(
            name="Primaria cotización API",
            defaults={
                "is_active": True,
            },
        )
        grade, _ = Grade.objects.get_or_create(
            name="4to Primaria cotización API",
            defaults={
                "order": 4,
                "is_active": True,
            },
        )
        area, _ = Area.objects.get_or_create(
            name="Matemática cotización API",
            defaults={
                "is_active": True,
            },
        )
        product, _ = Product.objects.get_or_create(
            provider=provider,
            name="Matemática 4 cotización API",
            defaults={
                "level": level,
                "grade": grade,
                "area": area,
                "is_active": True,
            },
        )

        return product

    def _create_quotation_via_api(self):
        product = self._create_quote_product()
        response = self.client.post(
            reverse(
                "crm:opportunity-quotations",
                args=[self.opportunity.id],
            ),
            {
                "notes": "Propuesta comercial API.",
                "sale_mode": "point_of_sale",
                "service_date": "2027-01-15",
                "items": [
                    {
                        "product": product.id,
                        "quantity": 60,
                        "pvp": "120.00",
                        "supplier_cost": "70.00",
                        "school_price": "90.00",
                        "parent_price": "110.00",
                        "school_commission": "5.00",
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)

        # Este helper conserva la cobertura del endpoint histórico de
        # creación manual, pero deja el registro listo para probar el
        # ciclo enviar/aceptar/reabrir con la regla comercial vigente:
        # antes de enviar, supervisión ya debe haber definido el
        # descuento editorial.
        quotation = self.opportunity.quotations.get(
            pk=response.data["id"],
        )
        quotation.items.update(
            supplier_discount_percent=Decimal("40.00"),
            supplier_cost=Decimal("72.00"),
        )

        return response

    def test_commercial_history_unifies_activity_and_quotation_events(self):
        self.authenticate(self.advisor)

        activity_response = self.client.post(
            reverse(
                "crm:opportunity-activities",
                args=[self.opportunity.id],
            ),
            {
                "activity_type": "call",
                "summary": "Llamada de seguimiento",
                "result": "El colegio solicita una propuesta.",
            },
            format="json",
        )
        self.assertEqual(activity_response.status_code, 201)

        quotation_response = self._create_quotation_via_api()
        quotation_id = quotation_response.data["id"]

        send_response = self.client.post(
            reverse(
                "crm:opportunity-send-quotation",
                args=[self.opportunity.id, quotation_id],
            ),
            {},
            format="json",
        )
        self.assertEqual(send_response.status_code, 200)

        accept_response = self.client.post(
            reverse(
                "crm:opportunity-accept-quotation",
                args=[self.opportunity.id, quotation_id],
            ),
            {},
            format="json",
        )
        self.assertEqual(accept_response.status_code, 200)

        response = self.client.get(
            reverse(
                "crm:opportunity-commercial-history",
                args=[self.opportunity.id],
            )
        )

        self.assertEqual(response.status_code, 200)

        event_types = {
            item["event_type"]
            for item in response.data
        }
        self.assertIn("call", event_types)
        self.assertIn("quotation_created", event_types)
        self.assertIn("quotation_sent", event_types)
        self.assertIn("quotation_accepted", event_types)

        sent_event = next(
            item
            for item in response.data
            if item["event_type"] == "quotation_sent"
        )
        self.assertEqual(
            sent_event["actor"]["username"],
            self.advisor.username,
        )
        self.assertEqual(sent_event["platform"], "Página Web")

    def test_school_history_keeps_activity_before_opportunity(self):
        self.authenticate(self.advisor)

        response = self.client.post(
            reverse(
                "crm:school-activities",
                args=[self.school.id],
            ),
            {
                "activity_type": "cold_visit",
                "summary": "Visita inicial al colegio",
                "result": "Se obtuvo el nombre del director.",
                "opportunity": None,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data["opportunity_id"])

        history_response = self.client.get(
            reverse(
                "crm:school-commercial-history",
                args=[self.school.id],
            )
        )

        self.assertEqual(history_response.status_code, 200)
        visit_events = [
            item
            for item in history_response.data
            if item["event_type"] == "cold_visit"
        ]
        self.assertEqual(len(visit_events), 1)
        self.assertEqual(
            visit_events[0]["title"],
            "Visita inicial al colegio",
        )

        opportunity_history = self.client.get(
            reverse(
                "crm:opportunity-commercial-history",
                args=[self.opportunity.id],
            )
        )
        self.assertEqual(opportunity_history.status_code, 200)
        self.assertNotIn(
            "cold_visit",
            {
                item["event_type"]
                for item in opportunity_history.data
            },
        )

    def test_activity_is_persisted_once_in_crm_history(self):
        self.authenticate(self.advisor)

        response = self.client.post(
            reverse(
                "crm:opportunity-activities",
                args=[self.opportunity.id],
            ),
            {
                "activity_type": "call",
                "summary": "Confirmar reunión",
                "result": "El director confirmó la reunión.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            CRMHistoryEvent.objects.filter(
                school=self.school,
                opportunity=self.opportunity,
                source_type="commercial_activity",
                source_id=response.data["id"],
                event_type="call",
            ).count(),
            1,
        )

        history_response = self.client.get(
            reverse(
                "crm:opportunity-commercial-history",
                args=[self.opportunity.id],
            )
        )
        call_events = [
            item
            for item in history_response.data
            if item["source_type"] == "commercial_activity"
            and item["source_id"] == response.data["id"]
            and item["event_type"] == "call"
        ]
        self.assertEqual(len(call_events), 1)

    def test_advisor_can_create_and_list_opportunity_quotation(self):
        self.authenticate(self.advisor)

        create_response = self._create_quotation_via_api()

        self.assertEqual(create_response.data["version"], 1)
        self.assertEqual(create_response.data["status"], "draft")
        self.assertEqual(len(create_response.data["items"]), 1)
        self.assertEqual(
            create_response.data["items"][0]["product_name_snapshot"],
            "Matemática 4 cotización API",
        )

        list_response = self.client.get(
            reverse(
                "crm:opportunity-quotations",
                args=[self.opportunity.id],
            )
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.data), 1)
        self.assertEqual(
            list_response.data[0]["id"],
            create_response.data["id"],
        )

    def test_quotation_api_send_and_accept_updates_opportunity(self):
        self.authenticate(self.advisor)
        create_response = self._create_quotation_via_api()
        quotation_id = create_response.data["id"]

        send_response = self.client.post(
            reverse(
                "crm:opportunity-send-quotation",
                args=[self.opportunity.id, quotation_id],
            ),
            {},
            format="json",
        )

        self.assertEqual(send_response.status_code, 200)
        self.assertEqual(send_response.data["status"], "sent")

        self.opportunity.refresh_from_db()
        self.assertEqual(
            self.opportunity.stage,
            self.quotation_stage,
        )

        accept_response = self.client.post(
            reverse(
                "crm:opportunity-accept-quotation",
                args=[self.opportunity.id, quotation_id],
            ),
            {},
            format="json",
        )

        self.assertEqual(accept_response.status_code, 200)
        self.assertEqual(
            accept_response.data["status"],
            "accepted",
        )

    def test_quotation_api_can_reopen_accepted_negotiation(self):
        self.authenticate(self.advisor)
        create_response = self._create_quotation_via_api()
        quotation_id = create_response.data["id"]

        self.client.post(
            reverse(
                "crm:opportunity-send-quotation",
                args=[self.opportunity.id, quotation_id],
            ),
            {},
            format="json",
        )
        self.client.post(
            reverse(
                "crm:opportunity-accept-quotation",
                args=[self.opportunity.id, quotation_id],
            ),
            {},
            format="json",
        )

        reopen_response = self.client.post(
            reverse(
                "crm:opportunity-reopen-quotation-negotiation",
                args=[self.opportunity.id, quotation_id],
            ),
            {
                "reason": "El colegio solicita una nueva propuesta.",
            },
            format="json",
        )

        self.assertEqual(reopen_response.status_code, 200)
        self.assertEqual(reopen_response.data["status"], "superseded")
        self.assertEqual(
            reopen_response.data["reopen_reason"],
            "El colegio solicita una nueva propuesta.",
        )
        self.assertIsNotNone(reopen_response.data["reopened_at"])
        self.assertIsNotNone(reopen_response.data["reopened_by"])

        create_again = self._create_quotation_via_api()
        self.assertEqual(create_again.status_code, 201)
        self.assertEqual(create_again.data["version"], 2)
        self.assertEqual(create_again.data["status"], "draft")

    def test_adoption_api_closes_opportunity_as_won(self):
        contact = SchoolContact.objects.create(
            school=self.school,
            full_name="Directora adopción API",
            position="Directora",
            is_primary=True,
            created_by=self.admin,
        )

        self.authenticate(self.advisor)
        create_response = self._create_quotation_via_api()
        quotation_id = create_response.data["id"]

        send_response = self.client.post(
            reverse(
                "crm:opportunity-send-quotation",
                args=[self.opportunity.id, quotation_id],
            ),
            {},
            format="json",
        )
        self.assertEqual(send_response.status_code, 200)

        accept_response = self.client.post(
            reverse(
                "crm:opportunity-accept-quotation",
                args=[self.opportunity.id, quotation_id],
            ),
            {},
            format="json",
        )
        self.assertEqual(accept_response.status_code, 200)

        adoption_response = self.client.post(
            reverse(
                "crm:opportunity-adoptions",
                args=[self.opportunity.id],
            ),
            {
                "quotation": quotation_id,
                "authorized_contact": contact.id,
                "signed_at": (
                    timezone.now() - timedelta(minutes=5)
                ).isoformat(),
                "notes": "Adopción confirmada en prueba API.",
            },
            format="json",
        )

        self.assertEqual(adoption_response.status_code, 201)
        self.assertEqual(
            adoption_response.data["authorized_contact"]["id"],
            contact.id,
        )
        self.assertEqual(
            len(adoption_response.data["items"]),
            1,
        )

        self.opportunity.refresh_from_db()
        self.assertEqual(
            self.opportunity.stage,
            self.won_stage,
        )
        self.assertIsNotNone(self.opportunity.closed_at)

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

    def test_school_location_filters_ignore_accents_and_case(self):
        SchoolCampus.objects.create(
            school=self.school,
            sequence=1,
            name="Sede principal",
            department="Junín",
            province="Huancayo",
            district="El Tambo",
            is_main=True,
            created_by=self.admin,
        )
        self.authenticate(self.advisor)

        response = self.client.get(
            reverse("crm:school-list"),
            {
                "department": "JUNIN",
                "province": "huancayo",
                "district": "EL TAMBO",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.school.id)

    def test_school_location_options_follow_loaded_geography(self):
        SchoolCampus.objects.create(
            school=self.school,
            sequence=1,
            name="Sede principal",
            department="Junín",
            province="Huancayo",
            district="El Tambo",
            is_main=True,
            created_by=self.admin,
        )
        self.authenticate(self.advisor)

        response = self.client.get(
            reverse("crm:school-location-options"),
            {
                "department": "junin",
                "province": "HUANCAYO",
                "is_active": "true",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["departments"], ["Junín"])
        self.assertEqual(response.data["provinces"], ["Huancayo"])
        self.assertEqual(response.data["districts"], ["El Tambo"])

    def test_new_contact_form_requires_commercial_fields(self):
        self.authenticate(self.advisor)

        response = self.client.post(
            reverse("crm:school-contacts", args=[self.school.id]),
            {
                "first_name": "María",
                "last_name": "Pérez",
                "position": "Director(a)",
                "whatsapp": "999888777",
                "email": "maria.perez@example.com",
                "decision_role": "decision_maker",
                "relationship_level": 3,
                "is_primary": True,
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["first_name"], "María")
        self.assertEqual(response.data["last_name"], "Pérez")
        self.assertEqual(response.data["full_name"], "María Pérez")
        self.assertEqual(response.data["phone"], "")

        invalid_response = self.client.post(
            reverse("crm:school-contacts", args=[self.school.id]),
            {
                "first_name": "Luis",
                "last_name": "Rojas",
                "position": "Coordinador(a)",
                "whatsapp": "999111222",
                "email": "",
                "decision_role": "influencer",
                "relationship_level": 2,
            },
            format="json",
        )

        self.assertEqual(invalid_response.status_code, 400)
        self.assertIn("email", invalid_response.data)

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

    def test_summary_exposes_weekly_operational_activity_counts(self):
        CommercialActivity.objects.create(
            school=self.school,
            opportunity=self.opportunity,
            performed_by=self.advisor,
            created_by=self.advisor,
            activity_type=CommercialActivity.ActivityType.CALL,
            summary="Llamada semanal",
            result="Contacto realizado.",
        )
        CommercialActivity.objects.create(
            school=self.school,
            opportunity=self.opportunity,
            performed_by=self.advisor,
            created_by=self.advisor,
            activity_type=CommercialActivity.ActivityType.VISIT,
            summary="Visita coordinada semanal",
            result="Reunión confirmada.",
        )

        self.authenticate(self.advisor)
        response = self.client.get(reverse("crm:summary"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["activities_week"], 2)
        self.assertEqual(response.data["activity_counts"]["call"], 1)
        self.assertEqual(response.data["activity_counts"]["visit"], 1)
        self.assertEqual(
            response.data["activity_counts"]["cold_visit"],
            0,
        )

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

    def test_school_contact_activity_auto_links_unique_open_opportunity(self):
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
        self.assertEqual(
            response.data["opportunity_id"],
            self.opportunity.id,
        )
        self.assertEqual(response.data["contact"]["id"], contact.id)

        self.opportunity.refresh_from_db()
        self.assertIsNotNone(self.opportunity.last_activity_at)

    def test_school_activity_can_explicitly_remain_without_opportunity(self):
        self.authenticate(self.advisor)

        response = self.client.post(
            reverse(
                "crm:school-activities",
                args=[self.school.id],
            ),
            {
                "activity_type": "cold_visit",
                "summary": "Visita en frío al colegio",
                "result": "No brindaron datos del directivo; se dejó material informativo.",
                "contact": None,
                "opportunity": None,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["school_id"], self.school.id)
        self.assertIsNone(response.data["opportunity_id"])
        self.assertIsNone(response.data["contact"])
        self.assertEqual(
            response.data["activity_type_display"],
            "Visita en frío",
        )

        self.opportunity.refresh_from_db()
        self.assertIsNone(self.opportunity.last_activity_at)

    def test_marking_school_primary_contact_fills_empty_open_opportunity(self):
        contact = SchoolContact.objects.create(
            school=self.school,
            full_name="Director principal CRM",
            position="Director",
            created_by=self.admin,
        )

        self.assertIsNone(self.opportunity.primary_contact)

        self.authenticate(self.advisor)
        response = self.client.patch(
            reverse("crm:contact-detail", args=[contact.id]),
            {
                "is_primary": True,
                "decision_role": "decision_maker",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_primary"])

        self.opportunity.refresh_from_db()
        self.assertEqual(
            self.opportunity.primary_contact_id,
            contact.id,
        )

    def test_primary_contact_sync_does_not_overwrite_existing_opportunity_contact(
        self,
    ):
        existing_contact = SchoolContact.objects.create(
            school=self.school,
            full_name="Directora oportunidad CRM",
            position="Directora",
            created_by=self.admin,
        )
        self.opportunity.primary_contact = existing_contact
        self.opportunity.save(update_fields=["primary_contact", "updated_at"])

        new_primary = SchoolContact.objects.create(
            school=self.school,
            full_name="Nuevo contacto principal CRM",
            position="Promotor",
            created_by=self.admin,
        )

        self.authenticate(self.advisor)
        response = self.client.patch(
            reverse("crm:contact-detail", args=[new_primary.id]),
            {"is_primary": True},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        self.opportunity.refresh_from_db()
        self.assertEqual(
            self.opportunity.primary_contact_id,
            existing_contact.id,
        )

    def test_school_activity_does_not_guess_between_open_opportunities(self):
        other_campaign = Campaign.objects.create(
            code="API-2028",
            name="Campaña API 2028",
            year=2028,
            status=Campaign.Status.PLANNING,
            created_by=self.admin,
        )
        Opportunity.objects.create(
            title="Oportunidad API 2028",
            school=self.school,
            campaign=other_campaign,
            pipeline=self.pipeline,
            stage=self.initial_stage,
            team=self.team,
            owner=self.advisor,
            created_by=self.admin,
        )

        self.authenticate(self.advisor)

        response = self.client.post(
            reverse(
                "crm:school-activities",
                args=[self.school.id],
            ),
            {
                "activity_type": "call",
                "summary": "Llamada general al colegio",
                "result": "Se coordinó una nueva conversación.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data["opportunity_id"])

    def test_school_task_auto_links_unique_open_opportunity(
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
                opportunity=self.opportunity,
                task_id=response.data["id"],
            ).exists()
        )

    def test_school_task_can_explicitly_remain_without_opportunity(self):
        self.authenticate(self.advisor)

        response = self.client.post(
            reverse(
                "crm:school-create-task",
                args=[self.school.id],
            ),
            {
                "title": "Volver a visitar el colegio",
                "opportunity": None,
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
                "commercial_action_type": "visit",
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
        self.assertEqual(
            response.data["results"][0]["commercial_action_type"],
            "visit",
        )
        self.assertEqual(
            response.data["results"][0]["commercial_action_type_display"],
            "Visita coordinada",
        )
        self.assertEqual(
            response.data["results"][0]["opportunity_id"],
            self.opportunity.id,
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

    def test_opportunity_list_exposes_nearest_next_activity(self):
        self.authenticate(self.advisor)

        later_at = timezone.now() + timedelta(days=3)
        sooner_at = timezone.now() + timedelta(days=1)

        task_response = self.client.post(
            reverse(
                "crm:opportunity-create-task",
                args=[self.opportunity.id],
            ),
            {
                "title": "Preparar propuesta futura",
                "due_at": later_at.isoformat(),
            },
            format="json",
        )
        event_response = self.client.post(
            reverse(
                "crm:opportunity-create-event",
                args=[self.opportunity.id],
            ),
            {
                "title": "Reunión con dirección",
                "start_at": sooner_at.isoformat(),
            },
            format="json",
        )

        self.assertEqual(task_response.status_code, 201)
        self.assertEqual(event_response.status_code, 201)

        response = self.client.get(
            reverse("crm:opportunity-list"),
        )

        self.assertEqual(response.status_code, 200)

        opportunity_data = next(
            item
            for item in response.data["results"]
            if item["id"] == self.opportunity.id
        )

        self.assertEqual(
            opportunity_data["next_activity"]["type"],
            "event",
        )
        self.assertEqual(
            opportunity_data["next_activity"]["title"],
            "Reunión con dirección",
        )
        self.assertEqual(
            opportunity_data["next_activity"]["id"],
            event_response.data["id"],
        )

    def test_school_event_preserves_commercial_activity_type(self):
        self.authenticate(self.advisor)

        start_at = timezone.now() + timedelta(days=2)
        response = self.client.post(
            reverse(
                "crm:school-create-event",
                args=[self.school.id],
            ),
            {
                "title": "Volver para presentación de producto",
                "start_at": start_at.isoformat(),
                "event_type": "cold_visit",
                "opportunity": self.opportunity.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["event_type"], "cold_visit")

        list_response = self.client.get(
            reverse("crm:opportunity-list"),
        )
        self.assertEqual(list_response.status_code, 200)

        opportunity_data = next(
            item
            for item in list_response.data["results"]
            if item["id"] == self.opportunity.id
        )
        self.assertEqual(
            opportunity_data["next_activity"]["type_display"],
            "Visita en frío",
        )

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

    def test_admin_can_create_commercial_team_with_members(self):
        self.authenticate(self.admin)

        response = self.client.post(
            reverse("crm:commercial-team-list"),
            {
                "name": "Equipo Centro",
                "description": "Equipo comercial de prueba.",
                "is_active": True,
                "supervisor_ids": [self.supervisor.id],
                "advisor_ids": [self.advisor.id],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["name"], "Equipo Centro")
        self.assertEqual(response.data["advisor_count"], 1)
        self.assertEqual(response.data["supervisor_count"], 1)

        team = CommercialTeam.objects.get(pk=response.data["id"])
        self.assertTrue(
            team.memberships.filter(
                user=self.supervisor,
                role=CommercialTeamMembership.Role.SUPERVISOR,
                is_active=True,
            ).exists()
        )
        self.assertTrue(
            team.memberships.filter(
                user=self.advisor,
                role=CommercialTeamMembership.Role.ADVISOR,
                is_active=True,
            ).exists()
        )

    def test_supervisor_creating_team_is_kept_as_supervisor(self):
        self.authenticate(self.supervisor)

        response = self.client.post(
            reverse("crm:commercial-team-list"),
            {
                "name": "Equipo Supervisor",
                "description": "",
                "is_active": True,
                "supervisor_ids": [],
                "advisor_ids": [self.advisor.id],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        team = CommercialTeam.objects.get(pk=response.data["id"])
        self.assertTrue(
            team.memberships.filter(
                user=self.supervisor,
                role=CommercialTeamMembership.Role.SUPERVISOR,
                is_active=True,
            ).exists()
        )

    def test_advisor_cannot_create_commercial_team(self):
        self.authenticate(self.advisor)

        response = self.client.post(
            reverse("crm:commercial-team-list"),
            {
                "name": "Equipo no permitido",
                "is_active": True,
                "supervisor_ids": [],
                "advisor_ids": [],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_team_eligible_members_separates_supervisors_and_advisors(self):
        self.authenticate(self.admin)

        response = self.client.get(
            reverse("crm:commercial-team-eligible-members")
        )

        self.assertEqual(response.status_code, 200)
        supervisor_ids = {
            user["id"]
            for user in response.data["supervisors"]
        }
        advisor_ids = {
            user["id"]
            for user in response.data["advisors"]
        }

        self.assertIn(self.supervisor.id, supervisor_ids)
        self.assertIn(self.advisor.id, advisor_ids)
        self.assertNotIn(self.supervisor.id, advisor_ids)

    def test_admin_can_assign_multiple_schools_in_one_request(self):
        extra_school = School.objects.create(
            name="Colegio API adicional",
            created_by=self.admin,
        )

        self.authenticate(self.admin)

        response = self.client.post(
            reverse("crm:school-assign-portfolio"),
            {
                "school_ids": [
                    self.school.id,
                    extra_school.id,
                ],
                "team": self.other_team.id,
                "owner": self.other_advisor.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["updated"], 2)

        self.school.refresh_from_db()
        extra_school.refresh_from_db()

        self.assertEqual(self.school.team_id, self.other_team.id)
        self.assertEqual(
            self.school.owner_id,
            self.other_advisor.id,
        )
        self.assertEqual(
            extra_school.team_id,
            self.other_team.id,
        )
        self.assertEqual(
            extra_school.owner_id,
            self.other_advisor.id,
        )

    def test_admin_can_assign_all_schools_matching_filters(self):
        first_school = School.objects.create(
            name="C3 Seleccion Norte",
            created_by=self.admin,
        )
        second_school = School.objects.create(
            name="C3 Seleccion Sur",
            created_by=self.admin,
        )

        self.authenticate(self.admin)

        response = self.client.post(
            reverse("crm:school-assign-portfolio"),
            {
                "selection_mode": "filters",
                "filters": {
                    "search": "C3 Seleccion",
                    "is_active": "true",
                },
                "team": self.other_team.id,
                "owner": self.other_advisor.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["updated"], 2)
        self.assertEqual(response.data["selection_mode"], "filters")

        first_school.refresh_from_db()
        second_school.refresh_from_db()
        self.school.refresh_from_db()

        self.assertEqual(first_school.team_id, self.other_team.id)
        self.assertEqual(first_school.owner_id, self.other_advisor.id)
        self.assertEqual(second_school.team_id, self.other_team.id)
        self.assertEqual(second_school.owner_id, self.other_advisor.id)
        self.assertEqual(self.school.team_id, self.team.id)
        self.assertEqual(self.school.owner_id, self.advisor.id)

    def test_admin_can_assign_school_portfolio(self):
        self.authenticate(self.admin)

        response = self.client.post(
            reverse("crm:school-assign-portfolio"),
            {
                "school_ids": [self.school.id],
                "team": self.other_team.id,
                "owner": self.other_advisor.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["updated"], 1)

        self.school.refresh_from_db()
        self.assertEqual(self.school.team_id, self.other_team.id)
        self.assertEqual(self.school.owner_id, self.other_advisor.id)

    def test_supervisor_can_assign_visible_school_inside_own_team(self):
        second_advisor = User.objects.create_user(
            username="crm-api-second-advisor",
            password="test-password",
        )
        grant_permission(second_advisor, "view_crm")
        grant_permission(second_advisor, "manage_schools")
        grant_permission(second_advisor, "manage_own_opportunities")
        CommercialTeamMembership.objects.create(
            team=self.team,
            user=second_advisor,
            role=CommercialTeamMembership.Role.ADVISOR,
            created_by=self.admin,
        )

        self.authenticate(self.supervisor)

        response = self.client.post(
            reverse("crm:school-assign-portfolio"),
            {
                "school_ids": [self.school.id],
                "team": self.team.id,
                "owner": second_advisor.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.school.refresh_from_db()
        self.assertEqual(self.school.team_id, self.team.id)
        self.assertEqual(self.school.owner_id, second_advisor.id)

    def test_supervisor_cannot_assign_school_to_unsupervised_team(self):
        self.authenticate(self.supervisor)

        response = self.client.post(
            reverse("crm:school-assign-portfolio"),
            {
                "school_ids": [self.school.id],
                "team": self.other_team.id,
                "owner": self.other_advisor.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_advisor_cannot_assign_school_portfolio(self):
        self.authenticate(self.advisor)

        response = self.client.post(
            reverse("crm:school-assign-portfolio"),
            {
                "school_ids": [self.school.id],
                "team": self.team.id,
                "owner": self.advisor.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_school_assignment_rejects_owner_outside_selected_team(self):
        self.authenticate(self.admin)

        response = self.client.post(
            reverse("crm:school-assign-portfolio"),
            {
                "school_ids": [self.school.id],
                "team": self.team.id,
                "owner": self.other_advisor.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("owner", response.data)

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


    def test_population_rejects_grade_from_another_level(self):
        primary = Level.objects.create(
            name="Primaria validación CRM",
            is_active=True,
        )
        initial_grade = Grade.objects.create(
            name="3 años incompatibilidad CRM",
            order=1,
            is_active=True,
        )

        self.authenticate(self.admin)
        response = self.client.patch(
            reverse(
                "crm:school-institutional-population",
                args=[self.school.id],
            ),
            {
                "levels": [
                    {
                        "level": primary.id,
                        "year": 2027,
                        "is_active": True,
                        "details": [
                            {
                                "grade": initial_grade.id,
                                "section_count": 1,
                                "students_per_section": 20,
                            }
                        ],
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            SchoolPopulationRecord.objects.filter(
                service__school=self.school,
                service__level=primary,
            ).exists()
        )

    def test_initial_population_rejects_non_standard_multigrade(self):
        initial = Level.objects.create(
            name="Inicial validación CRM",
            is_active=True,
        )
        multigrade = Grade.objects.create(
            name="Multigrado Inicial validación CRM",
            order=99,
            is_active=True,
        )

        self.authenticate(self.admin)
        response = self.client.patch(
            reverse(
                "crm:school-institutional-population",
                args=[self.school.id],
            ),
            {
                "levels": [
                    {
                        "level": initial.id,
                        "year": 2027,
                        "is_active": True,
                        "details": [
                            {
                                "grade": multigrade.id,
                                "section_count": 1,
                                "students_per_section": 20,
                            }
                        ],
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            SchoolPopulationRecord.objects.filter(
                service__school=self.school,
                service__level=initial,
            ).exists()
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

    def test_school_detail_consolidates_physical_population_by_level(self):
        primary = Level.objects.create(
            name="Primaria consolidada CRM",
            is_active=True,
        )
        main_campus = SchoolCampus.objects.create(
            school=self.school,
            sequence=1,
            name="Sede principal",
            address="Jr. Principal 100",
            is_main=True,
            created_by=self.admin,
        )
        second_campus = SchoolCampus.objects.create(
            school=self.school,
            sequence=2,
            name="Sede 2",
            address="Av. Secundaria 200",
            created_by=self.admin,
        )
        main_service = SchoolEducationalService.objects.create(
            school=self.school,
            campus=main_campus,
            level=primary,
            modular_code="7777001",
            created_by=self.admin,
        )
        second_service = SchoolEducationalService.objects.create(
            school=self.school,
            campus=second_campus,
            level=primary,
            modular_code="7777002",
            created_by=self.admin,
        )

        SchoolPopulationRecord.objects.create(
            service=main_service,
            year=2027,
            student_count=300,
            source="import",
            is_current=True,
            recorded_by=self.admin,
        )
        SchoolPopulationRecord.objects.create(
            service=second_service,
            year=2027,
            student_count=120,
            source="import",
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
            420,
        )
        self.assertEqual(response.data["segment"], "B")
        self.assertEqual(
            len(response.data["institutional_population"]),
            1,
        )
        self.assertEqual(
            response.data["institutional_population"][0]["student_count"],
            420,
        )
        self.assertEqual(
            response.data["institutional_population"][0]["source"],
            "consolidated",
        )

    def test_institutional_population_overrides_physical_fallback(self):
        primary = Level.objects.create(
            name="Primaria institucional CRM",
            is_active=True,
        )
        main_campus = SchoolCampus.objects.create(
            school=self.school,
            sequence=1,
            name="Sede principal",
            address="Jr. Principal 100",
            is_main=True,
            created_by=self.admin,
        )
        second_campus = SchoolCampus.objects.create(
            school=self.school,
            sequence=2,
            name="Sede 2",
            address="Av. Secundaria 200",
            created_by=self.admin,
        )

        for index, (campus, students) in enumerate(
            (
                (main_campus, 300),
                (second_campus, 120),
            ),
            start=1,
        ):
            service = SchoolEducationalService.objects.create(
                school=self.school,
                campus=campus,
                level=primary,
                modular_code=f"888800{index}",
                created_by=self.admin,
            )
            SchoolPopulationRecord.objects.create(
                service=service,
                year=2027,
                student_count=students,
                source="import",
                is_current=True,
                recorded_by=self.admin,
            )

        self.authenticate(self.admin)
        update_response = self.client.patch(
            reverse(
                "crm:school-institutional-population",
                args=[self.school.id],
            ),
            {
                "levels": [
                    {
                        "level": primary.id,
                        "year": 2027,
                        "is_active": True,
                        "student_count": 390,
                        "details": [],
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(
            update_response.data[0]["student_count"],
            390,
        )
        self.assertEqual(
            update_response.data[0]["source"],
            "institutional",
        )

        detail_response = self.client.get(
            reverse(
                "crm:school-detail",
                args=[self.school.id],
            )
        )

        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(
            detail_response.data["current_population_total"],
            390,
        )
        self.assertEqual(detail_response.data["segment"], "B")
        self.assertEqual(
            len(detail_response.data["educational_services"]),
            2,
        )
        self.assertTrue(
            SchoolEducationalService.objects.filter(
                school=self.school,
                campus__isnull=True,
                level=primary,
            ).exists()
        )

    def test_pending_population_is_not_treated_as_zero(self):
        primary = Level.objects.create(
            name="Primaria pendiente CRM",
            is_active=True,
        )
        secondary = Level.objects.create(
            name="Secundaria pendiente CRM",
            is_active=True,
        )

        self.authenticate(self.admin)
        update_response = self.client.patch(
            reverse(
                "crm:school-institutional-population",
                args=[self.school.id],
            ),
            {
                "levels": [
                    {
                        "level": primary.id,
                        "year": 2027,
                        "is_active": True,
                        "student_count": 300,
                        "details": [],
                    },
                    {
                        "level": secondary.id,
                        "year": 2027,
                        "is_active": True,
                        "student_count": None,
                        "details": [],
                    },
                ]
            },
            format="json",
        )

        self.assertEqual(update_response.status_code, 200)

        detail_response = self.client.get(
            reverse(
                "crm:school-detail",
                args=[self.school.id],
            )
        )

        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(
            detail_response.data["current_population_total"],
            300,
        )
        self.assertEqual(detail_response.data["segment"], "B")

        pending_level = next(
            item
            for item in detail_response.data["institutional_population"]
            if item["level"]["id"] == secondary.id
        )
        self.assertEqual(pending_level["status"], "pending")
        self.assertIsNone(pending_level["student_count"])

    def test_confirmed_zero_population_does_not_use_legacy_estimate(self):
        primary = Level.objects.create(
            name="Primaria cero CRM",
            is_active=True,
        )
        self.school.estimated_students = 999
        self.school.save(update_fields=["estimated_students", "updated_at"])

        self.authenticate(self.admin)
        update_response = self.client.patch(
            reverse(
                "crm:school-institutional-population",
                args=[self.school.id],
            ),
            {
                "levels": [
                    {
                        "level": primary.id,
                        "year": 2027,
                        "is_active": True,
                        "student_count": 0,
                        "details": [],
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(update_response.status_code, 200)

        detail_response = self.client.get(
            reverse(
                "crm:school-detail",
                args=[self.school.id],
            )
        )

        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(
            detail_response.data["current_population_total"],
            0,
        )
        self.assertEqual(detail_response.data["segment"], "OUT")

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


    def test_advisor_can_update_school_commercial_signals(self):
        self.authenticate(self.advisor)

        response = self.client.patch(
            reverse(
                "crm:school-commercial-profile",
                args=[self.school.id],
            ),
            {
                "campaign": self.campaign.id,
                "monthly_tuition": "450.00",
                "textbook_usage": "core",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["monthly_tuition"], "450.00")
        self.assertEqual(response.data["textbook_usage"], "core")
        self.assertEqual(
            response.data["textbook_usage_display"],
            "Utiliza textos principales",
        )
        self.assertEqual(response.data["priority"], "undefined")
        self.assertEqual(response.data["priority_score"], 0)
        self.assertIsNone(response.data["scored_at"])

        profile = self.school.commercial_profiles.get(
            campaign=self.campaign,
        )
        self.assertEqual(profile.monthly_tuition, Decimal("450.00"))
        self.assertEqual(profile.textbook_usage, "core")

    def test_school_commercial_signals_allow_unknown_tuition(self):
        self.authenticate(self.advisor)

        response = self.client.patch(
            reverse(
                "crm:school-commercial-profile",
                args=[self.school.id],
            ),
            {
                "campaign": self.campaign.id,
                "monthly_tuition": None,
                "textbook_usage": "unknown",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["monthly_tuition"])
        self.assertEqual(response.data["textbook_usage"], "unknown")

    def test_school_commercial_signals_reject_inactive_campaign(self):
        closed_campaign = Campaign.objects.create(
            code="API-CLOSED-2026",
            name="Campaña cerrada 2026",
            year=2026,
            status=Campaign.Status.CLOSED,
            created_by=self.admin,
        )
        self.authenticate(self.advisor)

        response = self.client.patch(
            reverse(
                "crm:school-commercial-profile",
                args=[self.school.id],
            ),
            {
                "campaign": closed_campaign.id,
                "monthly_tuition": "400.00",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_school_detail_prefers_active_commercial_profile(self):
        previous_campaign = Campaign.objects.create(
            code="API-HISTORY-2026",
            name="Campaña histórica 2026",
            year=2026,
            status=Campaign.Status.CLOSED,
            created_by=self.admin,
        )
        self.school.commercial_profiles.create(
            campaign=previous_campaign,
            monthly_tuition=Decimal("300.00"),
        )
        self.school.commercial_profiles.create(
            campaign=self.campaign,
            monthly_tuition=Decimal("450.00"),
        )

        self.authenticate(self.advisor)
        response = self.client.get(
            reverse("crm:school-detail", args=[self.school.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["commercial_profile"]["campaign"]["id"],
            self.campaign.id,
        )
        self.assertEqual(
            response.data["commercial_profile"]["monthly_tuition"],
            "450.00",
        )

    def test_school_score_is_calculated_when_required_signals_exist(self):
        primary, _ = Level.objects.get_or_create(
            name="Primaria score API",
            defaults={
                "is_active": True,
            },
        )

        self.authenticate(self.advisor)

        population_response = self.client.patch(
            reverse(
                "crm:school-institutional-population",
                args=[self.school.id],
            ),
            {
                "levels": [
                    {
                        "level": primary.id,
                        "year": 2027,
                        "is_active": True,
                        "student_count": 600,
                        "details": [],
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(population_response.status_code, 200)

        contact_response = self.client.post(
            reverse(
                "crm:school-contacts",
                args=[self.school.id],
            ),
            {
                "full_name": "Directora score",
                "position": "Directora",
                "decision_role": "decision_maker",
                "relationship_level": 4,
                "is_primary": True,
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(contact_response.status_code, 201)

        score_response = self.client.patch(
            reverse(
                "crm:school-commercial-profile",
                args=[self.school.id],
            ),
            {
                "campaign": self.campaign.id,
                "monthly_tuition": "650.00",
                "textbook_usage": "core",
                "commercial_affinity": "pedagogical",
            },
            format="json",
        )

        self.assertEqual(score_response.status_code, 200)
        self.assertEqual(score_response.data["priority_score"], 75)
        self.assertEqual(score_response.data["priority"], "high")
        self.assertEqual(
            score_response.data["commercial_affinity"],
            "pedagogical",
        )
        self.assertIsNotNone(score_response.data["scored_at"])
        self.assertEqual(
            score_response.data["score_reasons"]["status"],
            "scored",
        )

        components = {
            item["key"]: item["points"]
            for item in score_response.data["score_reasons"]["components"]
        }
        self.assertEqual(
            components,
            {
                "population": 26,
                "tuition": 16,
                "relationship": 18,
                "history": 0,
                "affinity": 15,
            },
        )

    def test_school_score_rewards_previous_accepted_quotation(self):
        previous_campaign = Campaign.objects.create(
            code="API-SCORE-HISTORY-2026",
            name="Campaña score histórica 2026",
            year=2026,
            status=Campaign.Status.CLOSED,
            created_by=self.admin,
        )
        previous_opportunity = Opportunity.objects.create(
            title="Oportunidad histórica score",
            school=self.school,
            campaign=previous_campaign,
            pipeline=self.pipeline,
            stage=self.initial_stage,
            team=self.team,
            owner=self.advisor,
            created_by=self.admin,
        )
        CommercialQuotation.objects.create(
            opportunity=previous_opportunity,
            version=1,
            status=CommercialQuotation.Status.ACCEPTED,
            school_name_snapshot=self.school.name,
            campaign_name_snapshot=previous_campaign.name,
            accepted_at=timezone.now(),
            created_by=self.admin,
        )

        primary, _ = Level.objects.get_or_create(
            name="Primaria historial score API",
            defaults={
                "is_active": True,
            },
        )

        self.authenticate(self.advisor)
        population_response = self.client.patch(
            reverse(
                "crm:school-institutional-population",
                args=[self.school.id],
            ),
            {
                "levels": [
                    {
                        "level": primary.id,
                        "year": 2027,
                        "is_active": True,
                        "student_count": 600,
                        "details": [],
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(population_response.status_code, 200)

        contact_response = self.client.post(
            reverse(
                "crm:school-contacts",
                args=[self.school.id],
            ),
            {
                "full_name": "Director historial score",
                "position": "Director",
                "decision_role": "decision_maker",
                "relationship_level": 4,
                "is_primary": True,
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(contact_response.status_code, 201)

        score_response = self.client.patch(
            reverse(
                "crm:school-commercial-profile",
                args=[self.school.id],
            ),
            {
                "campaign": self.campaign.id,
                "monthly_tuition": "650.00",
                "commercial_affinity": "pedagogical",
            },
            format="json",
        )

        self.assertEqual(score_response.status_code, 200)
        self.assertEqual(score_response.data["priority_score"], 87)
        components = {
            item["key"]: item
            for item in score_response.data["score_reasons"]["components"]
        }
        self.assertEqual(components["history"]["points"], 12)
        self.assertEqual(
            components["history"]["detail"],
            "Cotización aceptada en campaña anterior",
        )

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

    def test_school_activity_can_store_location_without_evidence(self):
        self.authenticate(self.advisor)

        response = self.client.post(
            reverse(
                "crm:school-activities",
                args=[self.school.id],
            ),
            {
                "activity_type": "cold_visit",
                "summary": "Visita geolocalizada",
                "result": "Se visitó el colegio para ubicar al directivo.",
                "opportunity": None,
                "latitude": "-12.065432",
                "longitude": "-75.205678",
                "location_accuracy_m": "18.25",
                "location_captured_at": timezone.now().isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["latitude"], "-12.065432")
        self.assertEqual(response.data["longitude"], "-75.205678")
        self.assertEqual(
            response.data["location_accuracy_m"],
            "18.25",
        )

        activity = CommercialActivity.objects.get(
            pk=response.data["id"],
        )
        self.assertEqual(
            activity.latitude,
            Decimal("-12.065432"),
        )
        self.assertEqual(
            activity.longitude,
            Decimal("-75.205678"),
        )
        self.assertEqual(activity.evidences.count(), 0)

    def test_school_activity_accepts_evidence_with_optional_location(self):
        self.authenticate(self.advisor)

        activity_response = self.client.post(
            reverse(
                "crm:school-activities",
                args=[self.school.id],
            ),
            {
                "activity_type": "visit",
                "summary": "Visita con evidencia",
                "result": "Se presentó la propuesta al colegio.",
                "opportunity": None,
            },
            format="json",
        )
        self.assertEqual(activity_response.status_code, 201)
        activity_id = activity_response.data["id"]

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                evidence_response = self.client.post(
                    reverse(
                        "crm:school-activity-evidence",
                        args=[self.school.id, activity_id],
                    ),
                    {
                        "file": SimpleUploadedFile(
                            "visita.jpg",
                            b"evidencia-de-prueba",
                            content_type="image/jpeg",
                        ),
                        "latitude": "-12.065000",
                        "longitude": "-75.205000",
                        "accuracy_m": "12.50",
                    },
                    format="multipart",
                )

                self.assertEqual(evidence_response.status_code, 201)
                self.assertEqual(
                    evidence_response.data["evidence_type"],
                    "photo",
                )
                self.assertEqual(
                    evidence_response.data["original_name"],
                    "visita.jpg",
                )
                self.assertEqual(
                    evidence_response.data["latitude"],
                    "-12.065000",
                )
                self.assertIn(
                    "/media/crm/activity-evidence/",
                    evidence_response.data["file_url"],
                )

                activities_response = self.client.get(
                    reverse(
                        "crm:school-activities",
                        args=[self.school.id],
                    ),
                    {"page_size": 50},
                )

                self.assertEqual(
                    activities_response.status_code,
                    200,
                )
                activities = activities_response.data.get(
                    "results",
                    activities_response.data,
                )
                activity = next(
                    item
                    for item in activities
                    if item["id"] == activity_id
                )
                self.assertEqual(len(activity["evidences"]), 1)

        history_response = self.client.get(
            reverse(
                "crm:school-commercial-history",
                args=[self.school.id],
            )
        )
        self.assertEqual(history_response.status_code, 200)
        self.assertTrue(
            any(
                item["event_type"] == "activity_evidence_added"
                for item in history_response.data
            )
        )

    def test_activity_evidence_rejects_unsupported_file_type(self):
        self.authenticate(self.advisor)

        activity_response = self.client.post(
            reverse(
                "crm:school-activities",
                args=[self.school.id],
            ),
            {
                "activity_type": "call",
                "summary": "Llamada de prueba",
                "result": "Contacto realizado.",
                "opportunity": None,
            },
            format="json",
        )
        self.assertEqual(activity_response.status_code, 201)

        response = self.client.post(
            reverse(
                "crm:school-activity-evidence",
                args=[self.school.id, activity_response.data["id"]],
            ),
            {
                "file": SimpleUploadedFile(
                    "archivo.exe",
                    b"contenido-no-permitido",
                    content_type="application/octet-stream",
                ),
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("file", response.data)

