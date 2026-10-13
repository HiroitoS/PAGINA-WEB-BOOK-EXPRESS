from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workspaces", "0004_alter_task_options_alter_workspacegroup_options"),
    ]

    operations = [
        migrations.AlterField(
            model_name="calendarevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("meeting", "Reunión"),
                    ("call", "Llamada"),
                    ("whatsapp", "WhatsApp"),
                    ("email", "Correo"),
                    ("visit", "Visita coordinada"),
                    ("cold_visit", "Visita en frío"),
                    ("presentation", "Presentación de producto"),
                    ("sample_delivery", "Entrega de muestra"),
                    ("sample_return", "Devolución de muestra"),
                    ("follow_up", "Seguimiento"),
                    ("training", "Capacitación"),
                    ("delivery", "Entrega"),
                    ("deadline", "Fecha límite"),
                    ("internal", "Interno"),
                    ("other", "Otro"),
                ],
                default="meeting",
                max_length=30,
                verbose_name="Tipo de evento",
            ),
        ),
    ]
