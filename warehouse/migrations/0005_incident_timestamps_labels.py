from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("warehouse", "0004_receiving_incident")]
    operations = [
        migrations.AlterField(
            model_name="receivingincident",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación"),
        ),
        migrations.AlterField(
            model_name="receivingincident",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización"),
        ),
    ]
