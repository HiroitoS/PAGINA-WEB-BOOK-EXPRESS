from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from openpyxl import Workbook
from rest_framework.test import APIClient

from catalog.models import Level
from crm.models import (
    CommercialTeam,
    CommercialTeamMembership,
    School,
    SchoolEducationalService,
)


User = get_user_model()


def grant_permission(user, codename):
    permission = Permission.objects.get(
        content_type__app_label="crm",
        codename=codename,
    )
    user.user_permissions.add(permission)


class SchoolImportApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            username="school-import-admin",
            email="school-import-admin@example.com",
            password="test-password",
        )
        self.supervisor = User.objects.create_user(
            username="school-import-supervisor",
            password="test-password",
        )
        self.advisor = User.objects.create_user(
            username="school-import-advisor",
            password="test-password",
        )

        for user in (self.supervisor, self.advisor):
            grant_permission(user, "view_crm")
            grant_permission(user, "manage_schools")

        grant_permission(self.supervisor, "supervise_crm")
        grant_permission(self.supervisor, "assign_schools")

        self.team = CommercialTeam.objects.create(
            code="IMPORT-TEAM",
            name="Equipo Importación",
            created_by=self.admin,
        )
        CommercialTeamMembership.objects.create(
            team=self.team,
            user=self.supervisor,
            role=CommercialTeamMembership.Role.SUPERVISOR,
            created_by=self.admin,
        )
        CommercialTeamMembership.objects.create(
            team=self.team,
            user=self.advisor,
            role=CommercialTeamMembership.Role.ADVISOR,
            created_by=self.admin,
        )

        for name in ("Inicial", "Primaria", "Secundaria"):
            Level.objects.get_or_create(
                name=name,
                defaults={"is_active": True},
            )

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def build_excel(self, rows):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Instituciones"
        sheet.append(
            [
                "Código modular",
                "Código de institución",
                "Nombre de IE",
                "Nivel/Modalidad",
                "Dependencia",
                "Dirección",
                "Departamento",
                "Provincia",
                "Distrito",
                "Alumnos",
            ]
        )

        for row in rows:
            sheet.append(row)

        output = BytesIO()
        workbook.save(output)
        output.seek(0)

        return SimpleUploadedFile(
            "BE - LISTADO DE LEADS 2027.xlsx",
            output.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )

    def preview(self, rows, user=None):
        self.authenticate(user or self.admin)
        return self.client.post(
            reverse("crm:school-import-preview"),
            {
                "file": self.build_excel(rows),
                "population_year": 2027,
            },
            format="multipart",
        )

    def test_preview_groups_levels_under_one_school(self):
        response = self.preview(
            [
                [
                    "1001",
                    "IE-001",
                    "Colegio Importado",
                    "Inicial",
                    "Privada",
                    "Av. Uno 123",
                    "Junín",
                    "Huancayo",
                    "Huancayo",
                    20,
                ],
                [
                    "1002",
                    "IE-001",
                    "Colegio Importado",
                    "Primaria",
                    "Privada",
                    "Av. Uno 123",
                    "Junín",
                    "Huancayo",
                    "Huancayo",
                    120,
                ],
                [
                    "1003",
                    "IE-001",
                    "Colegio Importado",
                    "Secundaria",
                    "Privada",
                    "Av. Uno 123",
                    "Junín",
                    "Huancayo",
                    "Huancayo",
                    90,
                ],
            ]
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["total_rows"], 3)
        self.assertEqual(response.data["total_schools"], 1)
        self.assertEqual(response.data["total_new"], 1)
        self.assertEqual(response.data["total_updated"], 0)
        self.assertEqual(response.data["total_errors"], 0)
        self.assertEqual(response.data["status"], "validated")

    def test_confirm_creates_school_levels_and_population(self):
        preview = self.preview(
            [
                [
                    "2001",
                    "IE-002",
                    "Colegio Confirmado",
                    "Inicial",
                    "Privada",
                    "Jr. Dos 456",
                    "Junín",
                    "Huancayo",
                    "El Tambo",
                    30,
                ],
                [
                    "2002",
                    "IE-002",
                    "Colegio Confirmado",
                    "Primaria",
                    "Privada",
                    "Jr. Dos 456",
                    "Junín",
                    "Huancayo",
                    "El Tambo",
                    150,
                ],
            ]
        )

        self.assertEqual(preview.status_code, 201)

        response = self.client.post(
            reverse(
                "crm:school-import-confirm",
                args=[preview.data["id"]],
            ),
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "imported")

        school = School.objects.get(
            institution_code="IE-002"
        )
        self.assertEqual(school.name, "Colegio Confirmado")
        self.assertEqual(school.dependency, "Privada")
        self.assertEqual(school.department, "Junín")
        self.assertEqual(school.province, "Huancayo")
        self.assertEqual(school.district, "El Tambo")
        self.assertEqual(school.estimated_students, 180)

        services = (
            SchoolEducationalService.objects
            .filter(school=school)
            .select_related("level")
            .order_by("level__name")
        )
        self.assertEqual(services.count(), 2)

        populations = {
            service.level.name: service.population_records.get(
                is_current=True
            ).student_count
            for service in services
        }
        self.assertEqual(
            populations,
            {
                "Inicial": 30,
                "Primaria": 150,
            },
        )

    def test_reimport_preserves_commercial_assignment(self):
        school = School.objects.create(
            institution_code="IE-003",
            name="Colegio Existente",
            team=self.team,
            owner=self.advisor,
            created_by=self.admin,
        )

        preview = self.preview(
            [
                [
                    "3001",
                    "IE-003",
                    "Colegio Existente Actualizado",
                    "Primaria",
                    "Privada",
                    "Calle Tres 789",
                    "Junín",
                    "Huancayo",
                    "Chilca",
                    220,
                ],
            ]
        )

        self.assertEqual(preview.status_code, 201)
        self.assertEqual(preview.data["total_updated"], 1)

        response = self.client.post(
            reverse(
                "crm:school-import-confirm",
                args=[preview.data["id"]],
            ),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        school.refresh_from_db()
        self.assertEqual(
            school.name,
            "Colegio Existente Actualizado",
        )
        self.assertEqual(school.team_id, self.team.id)
        self.assertEqual(school.owner_id, self.advisor.id)

    def test_duplicate_school_level_blocks_confirmation(self):
        preview = self.preview(
            [
                [
                    "4001",
                    "IE-004",
                    "Colegio Duplicado",
                    "Primaria",
                    "Privada",
                    "Av. Cuatro",
                    "Junín",
                    "Huancayo",
                    "Huancayo",
                    100,
                ],
                [
                    "4002",
                    "IE-004",
                    "Colegio Duplicado",
                    "Primaria",
                    "Privada",
                    "Av. Cuatro",
                    "Junín",
                    "Huancayo",
                    "Huancayo",
                    120,
                ],
            ]
        )

        self.assertEqual(preview.status_code, 201)
        self.assertGreater(preview.data["total_errors"], 0)

        response = self.client.post(
            reverse(
                "crm:school-import-confirm",
                args=[preview.data["id"]],
            ),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_advisor_cannot_import_schools(self):
        response = self.preview(
            [
                [
                    "5001",
                    "IE-005",
                    "Colegio Restringido",
                    "Primaria",
                    "Privada",
                    "Av. Cinco",
                    "Junín",
                    "Huancayo",
                    "Huancayo",
                    90,
                ],
            ],
            user=self.advisor,
        )

        self.assertEqual(response.status_code, 403)
