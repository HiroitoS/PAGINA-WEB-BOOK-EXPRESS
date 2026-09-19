import django.db.models.deletion
from django.db import migrations, models


def move_service_school_from_campus(apps, schema_editor):
    SchoolEducationalService = apps.get_model("crm", "SchoolEducationalService")

    for service in SchoolEducationalService.objects.select_related("campus").all():
        service.school_id = service.campus.school_id
        service.save(update_fields=["school_id"])


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0004_schoolcampus_schoolcommercialprofile_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="schooleducationalservice",
            name="school",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="educational_services",
                to="crm.school",
                verbose_name="Colegio",
            ),
        ),
        migrations.RunPython(
            move_service_school_from_campus,
            migrations.RunPython.noop,
        ),
        migrations.RemoveIndex(
            model_name="schooleducationalservice",
            name="crm_service_campus_active_idx",
        ),
        migrations.RemoveField(
            model_name="schooleducationalservice",
            name="campus",
        ),
        migrations.AlterField(
            model_name="schooleducationalservice",
            name="school",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="educational_services",
                to="crm.school",
                verbose_name="Colegio",
            ),
        ),
        migrations.AddIndex(
            model_name="schooleducationalservice",
            index=models.Index(
                fields=["school", "is_active"],
                name="crm_service_school_active_idx",
            ),
        ),
        migrations.DeleteModel(
            name="SchoolCampus",
        ),
    ]
