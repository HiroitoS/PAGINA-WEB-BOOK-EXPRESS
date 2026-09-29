# Generated for Book Express CRM activity types.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0021_commercialquotation_reopening"),
    ]

    operations = [
        migrations.AlterField(
            model_name="commercialactivity",
            name="activity_type",
            field=models.CharField(
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
                max_length=30,
                verbose_name="Tipo de actividad",
            ),
        ),
    ]
}
