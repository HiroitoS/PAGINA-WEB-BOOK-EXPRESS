from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0029_commercialquotation_internal_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="commercialquotation",
            name="sale_mode",
            field=models.CharField(
                blank=True,
                choices=[
                    ("point_of_sale", "Punto de venta / librería"),
                    ("fair", "Feria"),
                    ("consignment", "Consignación"),
                ],
                db_index=True,
                default="",
                max_length=20,
                verbose_name="Modalidad de venta",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotation",
            name="service_date",
            field=models.DateField(
                blank=True,
                null=True,
                verbose_name="Fecha de atención",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotation",
            name="fair_start_time",
            field=models.TimeField(
                blank=True,
                null=True,
                verbose_name="Hora de inicio de feria",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotation",
            name="fair_end_time",
            field=models.TimeField(
                blank=True,
                null=True,
                verbose_name="Hora de fin de feria",
            ),
        ),
        migrations.AddField(
            model_name="adoption",
            name="advisor_phone_snapshot",
            field=models.CharField(
                blank=True,
                default="",
                max_length=30,
                verbose_name="Celular del asesor al confirmar",
            ),
        ),
        migrations.AddField(
            model_name="adoption",
            name="advisor_whatsapp_snapshot",
            field=models.CharField(
                blank=True,
                default="",
                max_length=30,
                verbose_name="WhatsApp del asesor al confirmar",
            ),
        ),
        migrations.AddField(
            model_name="adoption",
            name="authorized_contact_position_snapshot",
            field=models.CharField(
                blank=True,
                default="",
                max_length=120,
                verbose_name="Cargo del directivo al confirmar",
            ),
        ),
        migrations.AddField(
            model_name="adoption",
            name="authorized_contact_phone_snapshot",
            field=models.CharField(
                blank=True,
                default="",
                max_length=30,
                verbose_name="Teléfono del directivo al confirmar",
            ),
        ),
        migrations.AddField(
            model_name="adoption",
            name="authorized_contact_email_snapshot",
            field=models.EmailField(
                blank=True,
                default="",
                max_length=254,
                verbose_name="Correo del directivo al confirmar",
            ),
        ),
        migrations.AddField(
            model_name="adoption",
            name="sale_mode",
            field=models.CharField(
                blank=True,
                choices=[
                    ("point_of_sale", "Punto de venta / librería"),
                    ("fair", "Feria"),
                    ("consignment", "Consignación"),
                ],
                db_index=True,
                default="",
                max_length=20,
                verbose_name="Modalidad de venta",
            ),
        ),
        migrations.AddField(
            model_name="adoption",
            name="service_date",
            field=models.DateField(
                blank=True,
                null=True,
                verbose_name="Fecha de atención",
            ),
        ),
        migrations.AddField(
            model_name="adoption",
            name="fair_start_time",
            field=models.TimeField(
                blank=True,
                null=True,
                verbose_name="Hora de inicio de feria",
            ),
        ),
        migrations.AddField(
            model_name="adoption",
            name="fair_end_time",
            field=models.TimeField(
                blank=True,
                null=True,
                verbose_name="Hora de fin de feria",
            ),
        ),
    ]
