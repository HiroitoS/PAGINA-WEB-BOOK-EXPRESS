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
    SchoolCampus,
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
    DEFAULT_HEADERS = [
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

    def build_excel(self, rows, headers=None):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Instituciones"
        sheet.append(headers or self.DEFAULT_HEADERS)

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

    def preview(self, rows, user=None, headers=None):
        self.authenticate(user or self.admin)
        return self.client.post(
            reverse("crm:school-import-preview"),
            {
                "file": self.build_excel(rows, headers=headers),
                "population_year": 2027,
            },
            format="multipart",
        )

    def confirm(self, preview):
        return self.client.post(
            reverse(
                "crm:school-import-confirm",
                args=[preview.data["id"]],
            ),
            {},
            format="json",
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
        self.assertEqual(response.data["total_warnings"], 0)
        self.assertEqual(response.data["total_errors"], 0)
        self.assertEqual(response.data["status"], "validated")

    def test_confirm_creates_school_campus_levels_and_population(self):
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

        response = self.confirm(preview)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "imported")

        school = School.objects.get(institution_code="IE-002")
        self.assertTrue(school.book_express_code.startswith("BE-IE-"))
        self.assertEqual(school.name, "Colegio Confirmado")
        self.assertEqual(school.dependency, "Privada")
        self.assertEqual(school.department, "Junín")
        self.assertEqual(school.province, "Huancayo")
        self.assertEqual(school.district, "El Tambo")
        self.assertEqual(school.estimated_students, 180)

        campus = school.campuses.get()
        self.assertTrue(campus.is_main)
        self.assertEqual(campus.address, "Jr. Dos 456")
        self.assertEqual(campus.district, "El Tambo")
        self.assertTrue(
            campus.book_express_code.endswith("-S01")
        )

        services = (
            SchoolEducationalService.objects
            .filter(school=school)
            .select_related("campus", "level")
            .order_by("level__name")
        )
        self.assertEqual(services.count(), 2)
        self.assertTrue(
            all(service.campus_id == campus.id for service in services)
        )

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

        response = self.confirm(preview)
        self.assertEqual(response.status_code, 200)

        school.refresh_from_db()
        self.assertEqual(
            school.name,
            "Colegio Existente Actualizado",
        )
        self.assertEqual(school.team_id, self.team.id)
        self.assertEqual(school.owner_id, self.advisor.id)

    def test_same_campus_and_level_conflict_blocks_confirmation(self):
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
        self.assertEqual(preview.data["status"], "error")

        response = self.confirm(preview)
        self.assertEqual(response.status_code, 400)

    def test_missing_official_codes_are_warnings_not_errors(self):
        preview = self.preview(
            [
                [
                    "",
                    "",
                    "Colegio Sin Códigos",
                    "Primaria",
                    "Privada",
                    "Av. Libre 100",
                    "Junín",
                    "Huancayo",
                    "El Tambo",
                    80,
                ],
            ]
        )

        self.assertEqual(preview.status_code, 201)
        self.assertEqual(preview.data["total_errors"], 0)
        self.assertGreater(preview.data["total_warnings"], 0)
        self.assertEqual(preview.data["status"], "validated")
        self.assertTrue(preview.data["rows"][0]["warnings"])

        response = self.confirm(preview)
        self.assertEqual(response.status_code, 200)

        school = School.objects.get(name="Colegio Sin Códigos")
        self.assertIsNone(school.institution_code)
        self.assertTrue(school.book_express_code.startswith("BE-IE-"))

        service = school.educational_services.get()
        self.assertIsNone(service.modular_code)

    def test_missing_population_is_warning_and_school_is_imported(self):
        preview = self.preview(
            [
                [
                    "5200001",
                    "26552001",
                    "Colegio Población Pendiente",
                    "Primaria",
                    "Particular",
                    "Av. Pendiente 100",
                    "Junín",
                    "Huancayo",
                    "El Tambo",
                    "",
                ],
            ]
        )

        self.assertEqual(preview.status_code, 201)
        self.assertEqual(preview.data["status"], "validated")
        self.assertEqual(preview.data["total_errors"], 0)
        self.assertGreater(preview.data["total_warnings"], 0)

        response = self.confirm(preview)

        self.assertEqual(response.status_code, 200)
        school = School.objects.get(institution_code="26552001")
        self.assertIsNone(school.estimated_students)
        service = school.educational_services.get()
        self.assertFalse(service.population_records.exists())

    def test_exact_duplicate_is_warning_and_is_imported_once(self):
        row = [
            "5100001",
            "26550001",
            "Colegio Repetido",
            "Primaria",
            "Particular",
            "Jr. Repetido 100",
            "Junín",
            "Huancayo",
            "El Tambo",
            140,
        ]
        preview = self.preview([row, list(row)])

        self.assertEqual(preview.status_code, 201)
        self.assertEqual(preview.data["total_errors"], 0)
        self.assertGreater(preview.data["total_warnings"], 0)
        self.assertEqual(preview.data["status"], "validated")

        response = self.confirm(preview)
        self.assertEqual(response.status_code, 200)

        school = School.objects.get(institution_code="26550001")
        self.assertEqual(school.campuses.count(), 1)
        self.assertEqual(school.educational_services.count(), 1)
        self.assertEqual(school.estimated_students, 140)

    def test_two_campuses_with_distinct_modular_codes_are_preserved(self):
        preview = self.preview(
            [
                [
                    "6100001",
                    "26560001",
                    "Colegio Dos Sedes",
                    "Primaria",
                    "Particular",
                    "Jr. Sede Uno 100",
                    "Junín",
                    "Huancayo",
                    "Huancayo",
                    120,
                ],
                [
                    "6100002",
                    "26560001",
                    "Colegio Dos Sedes",
                    "Primaria",
                    "Particular",
                    "Av. Sede Dos 200",
                    "Junín",
                    "Huancayo",
                    "El Tambo",
                    90,
                ],
            ]
        )

        self.assertEqual(preview.status_code, 201)
        self.assertEqual(preview.data["total_errors"], 0)
        self.assertEqual(preview.data["status"], "validated")

        response = self.confirm(preview)
        self.assertEqual(response.status_code, 200)

        school = School.objects.get(institution_code="26560001")
        campuses = list(school.campuses.order_by("sequence"))
        self.assertEqual(len(campuses), 2)
        self.assertEqual(
            {campus.address for campus in campuses},
            {"Jr. Sede Uno 100", "Av. Sede Dos 200"},
        )
        self.assertEqual(school.educational_services.count(), 2)
        self.assertEqual(school.estimated_students, 210)

        populations = sorted(
            record.student_count
            for service in school.educational_services.all()
            for record in service.population_records.filter(
                is_current=True
            )
        )
        self.assertEqual(populations, [90, 120])

    def test_same_modular_code_in_two_addresses_is_imported_as_pending(self):
        preview = self.preview(
            [
                [
                    "1255710",
                    "26522382",
                    "PRAXIS LA ESPERANZA",
                    "Secundaria",
                    "Particular",
                    "JIRON PUNO 180",
                    "Junín",
                    "Huancayo",
                    "Huancayo",
                    500,
                ],
                [
                    "1255710",
                    "26522382",
                    "PRAXIS LA ESPERANZA",
                    "Secundaria",
                    "Particular",
                    "JIRON PACHACUTEC 550",
                    "Junín",
                    "Huancayo",
                    "El Tambo",
                    581,
                ],
            ]
        )

        self.assertEqual(preview.status_code, 201)
        self.assertEqual(preview.data["status"], "validated")
        self.assertEqual(preview.data["total_errors"], 0)
        self.assertGreaterEqual(preview.data["total_warnings"], 2)
        self.assertIn(
            "pendiente de validar",
            " ".join(preview.data["rows"][0]["warnings"]),
        )

        response = self.confirm(preview)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "imported")

        school = School.objects.get(institution_code="26522382")
        self.assertEqual(school.campuses.count(), 2)
        self.assertEqual(school.educational_services.count(), 2)
        self.assertTrue(
            all(
                service.modular_code is None
                for service in school.educational_services.all()
            )
        )
        self.assertEqual(school.estimated_students, 1081)

    def test_real_excel_header_style_and_leading_zero_modular_code(self):
        headers = [
            "Código modular",
            "Código de institución",
            "Nombre de IE",
            "Nivel / Modalidad",
            "Dependencia",
            "Dirección de IE",
            "Departamento / Provincia / Distrito",
            "Alumnos (Censo educativo 2026)",
        ]
        preview = self.preview(
            [
                [
                    918706,
                    26522382,
                    "PRAXIS LA ESPERANZA",
                    "Primaria",
                    "Particular",
                    "JIRON PACHACUTEC 550",
                    "Junín / Huancayo / El Tambo",
                    363,
                ],
            ],
            headers=headers,
        )

        self.assertEqual(preview.status_code, 201)
        self.assertEqual(preview.data["total_errors"], 0)
        self.assertEqual(
            preview.data["rows"][0]["modular_code"],
            "0918706",
        )
        self.assertEqual(
            preview.data["rows"][0]["institution_code"],
            "26522382",
        )

        response = self.confirm(preview)
        self.assertEqual(response.status_code, 200)

        school = School.objects.get(institution_code="26522382")
        campus = school.campuses.get()
        service = school.educational_services.get()

        self.assertEqual(campus.department, "Junín")
        self.assertEqual(campus.province, "Huancayo")
        self.assertEqual(campus.district, "El Tambo")
        self.assertEqual(service.modular_code, "0918706")

    def test_partial_import_keeps_conflicting_school_out(self):
        preview = self.preview(
            [
                [
                    "7000001",
                    "26570001",
                    "Colegio Listo",
                    "Primaria",
                    "Particular",
                    "Jr. Listo 100",
                    "Junín",
                    "Huancayo",
                    "El Tambo",
                    140,
                ],
                [
                    "7000002",
                    "26570002",
                    "Colegio Pendiente",
                    "Primaria",
                    "Particular",
                    "Jr. Pendiente 200",
                    "Junín",
                    "Huancayo",
                    "El Tambo",
                    100,
                ],
                [
                    "7000002",
                    "26570002",
                    "Colegio Pendiente",
                    "Primaria",
                    "Particular",
                    "Jr. Pendiente 200",
                    "Junín",
                    "Huancayo",
                    "El Tambo",
                    120,
                ],
            ]
        )

        self.assertEqual(preview.status_code, 201)
        self.assertEqual(preview.data["status"], "error")
        self.assertEqual(preview.data["total_new"], 1)
        self.assertGreater(preview.data["total_errors"], 0)

        response = self.confirm(preview)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "partial")
        self.assertTrue(
            School.objects.filter(
                institution_code="26570001"
            ).exists()
        )
        self.assertFalse(
            School.objects.filter(
                institution_code="26570002"
            ).exists()
        )

        pending_row = next(
            row
            for row in response.data["rows"]
            if row["institution_code"] == "26570002"
        )
        self.assertFalse(pending_row["processed"])

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
