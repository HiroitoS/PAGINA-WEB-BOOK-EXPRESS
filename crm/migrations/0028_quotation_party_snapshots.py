from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0027_adoptionitem_supplier_discount_percent"),
    ]

    operations = [
        migrations.AddField(
            model_name="commercialquotation",
            name="advisor_name_snapshot",
            field=models.CharField(
                blank=True,
                default="",
                max_length=180,
                verbose_name="Asesor al cotizar",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotation",
            name="advisor_phone_snapshot",
            field=models.CharField(
                blank=True,
                default="",
                max_length=30,
                verbose_name="Celular del asesor al cotizar",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotation",
            name="advisor_whatsapp_snapshot",
            field=models.CharField(
                blank=True,
                default="",
                max_length=30,
                verbose_name="WhatsApp del asesor al cotizar",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotation",
            name="primary_contact_email_snapshot",
            field=models.EmailField(
                blank=True,
                default="",
                max_length=254,
                verbose_name="Correo del contacto al cotizar",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotation",
            name="primary_contact_name_snapshot",
            field=models.CharField(
                blank=True,
                default="",
                max_length=180,
                verbose_name="Contacto al cotizar",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotation",
            name="primary_contact_phone_snapshot",
            field=models.CharField(
                blank=True,
                default="",
                max_length=30,
                verbose_name="Teléfono del contacto al cotizar",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotation",
            name="primary_contact_position_snapshot",
            field=models.CharField(
                blank=True,
                default="",
                max_length=120,
                verbose_name="Cargo del contacto al cotizar",
            ),
        ),
    ]
