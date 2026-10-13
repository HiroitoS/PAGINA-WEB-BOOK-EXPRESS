from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0039_schoolcontact_first_name_last_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="crmworkitemlink",
            name="commercial_action_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("call", "Llamada"),
                    ("whatsapp", "WhatsApp"),
                    ("email", "Correo"),
                    ("meeting", "Reunión"),
                    ("visit", "Visita coordinada"),
                    ("cold_visit", "Visita en frío"),
                    ("presentation", "Presentación de producto"),
                    ("sample_delivery", "Entrega de muestra"),
                    ("sample_return", "Devolución de muestra"),
                    ("follow_up", "Seguimiento"),
                    ("other", "Otro"),
                ],
                default="",
                max_length=30,
                verbose_name="Próxima acción comercial",
            ),
        ),
    ]
