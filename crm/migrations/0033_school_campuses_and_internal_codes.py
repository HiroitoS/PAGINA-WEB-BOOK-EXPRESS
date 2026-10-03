# Hand-authored migration for school campuses and internal Book Express codes.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_school_codes_and_campuses(apps, schema_editor):
    School = apps.get_model("crm", "School")
    SchoolCampus = apps.get_model("crm", "SchoolCampus")
    SchoolEducationalService = apps.get_model(
        "crm",
        "SchoolEducationalService",
    )

    for school in School.objects.all().order_by("id"):
        code = school.book_express_code or f"BE-IE-{school.id:06d}"

        if school.book_express_code != code:
            School.objects.filter(pk=school.pk).update(
                book_express_code=code,
            )

        campus, _ = SchoolCampus.objects.get_or_create(
            school_id=school.id,
            sequence=1,
            defaults={
                "name": "Sede principal",
                "address": school.address or "",
                "reference": school.reference or "",
                "department": school.department or "",
                "province": school.province or "",
                "district": school.district or "",
                "is_main": True,
                "is_active": True,
                "created_by_id": school.created_by_id,
            },
        )

        SchoolEducationalService.objects.filter(
            school_id=school.id,
            campus__isnull=True,
        ).update(campus_id=campus.id)


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0032_school_import_and_dependency"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="school",
            name="book_express_code",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=24,
                null=True,
                unique=True,
                verbose_name="Código Book Express",
            ),
        ),
        migrations.CreateModel(
            name="SchoolCampus",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="Fecha de creación",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        verbose_name="Fecha de actualización",
                    ),
                ),
                (
                    "sequence",
                    models.PositiveSmallIntegerField(
                        default=1,
                        verbose_name="Número de sede",
                    ),
                ),
                (
                    "name",
                    models.CharField(
                        default="Sede principal",
                        max_length=150,
                        verbose_name="Nombre de la sede",
                    ),
                ),
                (
                    "address",
                    models.CharField(
                        blank=True,
                        max_length=250,
                        verbose_name="Dirección",
                    ),
                ),
                (
                    "reference",
                    models.CharField(
                        blank=True,
                        max_length=250,
                        verbose_name="Referencia",
                    ),
                ),
                (
                    "department",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        max_length=100,
                        verbose_name="Departamento",
                    ),
                ),
                (
                    "province",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        max_length=100,
                        verbose_name="Provincia",
                    ),
                ),
                (
                    "district",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        max_length=100,
                        verbose_name="Distrito",
                    ),
                ),
                (
                    "is_main",
                    models.BooleanField(
                        default=False,
                        verbose_name="Sede principal",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        verbose_name="Activo",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_crm_school_campuses",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Creado por",
                    ),
                ),
                (
                    "school",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="campuses",
                        to="crm.school",
                        verbose_name="Colegio",
                    ),
                ),
            ],
            options={
                "verbose_name": "Sede de colegio",
                "verbose_name_plural": "Sedes de colegios",
                "ordering": ["school__name", "sequence", "id"],
            },
        ),
        migrations.AddField(
            model_name="schooleducationalservice",
            name="campus",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="educational_services",
                to="crm.schoolcampus",
                verbose_name="Sede",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="schooleducationalservice",
            name="crm_service_unique_school_level",
        ),
        migrations.RunPython(
            backfill_school_codes_and_campuses,
            migrations.RunPython.noop,
        ),
        migrations.AddIndex(
            model_name="schoolcampus",
            index=models.Index(
                fields=["school", "is_active"],
                name="crm_campus_school_active_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="schoolcampus",
            index=models.Index(
                fields=["department", "province", "district"],
                name="crm_campus_location_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="schoolcampus",
            constraint=models.UniqueConstraint(
                fields=("school", "sequence"),
                name="crm_campus_unique_school_sequence",
            ),
        ),
        migrations.AddConstraint(
            model_name="schoolcampus",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_main", True)),
                fields=("school",),
                name="crm_campus_one_main_per_school",
            ),
        ),
        migrations.AddIndex(
            model_name="schooleducationalservice",
            index=models.Index(
                fields=["campus", "is_active"],
                name="crm_service_campus_active_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="schooleducationalservice",
            constraint=models.UniqueConstraint(
                condition=models.Q(("campus__isnull", True)),
                fields=("school", "level"),
                name="crm_service_unique_school_level_legacy",
            ),
        ),
        migrations.AddConstraint(
            model_name="schooleducationalservice",
            constraint=models.UniqueConstraint(
                condition=models.Q(("campus__isnull", False)),
                fields=("campus", "level"),
                name="crm_service_unique_campus_level",
            ),
        ),
    ]
