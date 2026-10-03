from django.db import migrations, models
import django.db.models.deletion


def populate_school_context(apps, schema_editor):
    CommercialActivity = apps.get_model("crm", "CommercialActivity")
    CRMWorkItemLink = apps.get_model("crm", "CRMWorkItemLink")

    activities = CommercialActivity.objects.select_related(
        "opportunity"
    ).all()

    for activity in activities.iterator():
        if activity.opportunity_id:
            activity.school_id = activity.opportunity.school_id
            activity.save(update_fields=["school"])

    links = CRMWorkItemLink.objects.select_related(
        "opportunity",
        "origin_activity",
    ).all()

    for link in links.iterator():
        update_fields = []

        if link.opportunity_id:
            link.school_id = link.opportunity.school_id
            update_fields.append("school")

        if (
            link.origin_activity_id
            and link.origin_activity.contact_id
        ):
            link.contact_id = link.origin_activity.contact_id
            update_fields.append("contact")

        if update_fields:
            link.save(update_fields=update_fields)


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0015_schoolcontact_decision_context"),
    ]

    operations = [
        migrations.AddField(
            model_name="commercialactivity",
            name="school",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="commercial_activities",
                to="crm.school",
                verbose_name="Colegio",
            ),
        ),
        migrations.AlterField(
            model_name="commercialactivity",
            name="opportunity",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="commercial_activities",
                to="crm.opportunity",
                verbose_name="Oportunidad",
            ),
        ),
        migrations.AddField(
            model_name="crmworkitemlink",
            name="contact",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="crm_work_item_links",
                to="crm.schoolcontact",
                verbose_name="Contacto del colegio",
            ),
        ),
        migrations.AddField(
            model_name="crmworkitemlink",
            name="school",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="crm_work_item_links",
                to="crm.school",
                verbose_name="Colegio",
            ),
        ),
        migrations.AlterField(
            model_name="crmworkitemlink",
            name="opportunity",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="work_item_links",
                to="crm.opportunity",
                verbose_name="Oportunidad",
            ),
        ),
        migrations.RunPython(
            populate_school_context,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="commercialactivity",
            name="school",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="commercial_activities",
                to="crm.school",
                verbose_name="Colegio",
            ),
        ),
        migrations.AlterField(
            model_name="crmworkitemlink",
            name="school",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="crm_work_item_links",
                to="crm.school",
                verbose_name="Colegio",
            ),
        ),
        migrations.AddIndex(
            model_name="commercialactivity",
            index=models.Index(
                fields=["school", "-occurred_at"],
                name="crm_act_school_date_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="crmworkitemlink",
            index=models.Index(
                fields=["school", "-created_at"],
                name="crm_work_school_date_idx",
            ),
        ),
    ]
