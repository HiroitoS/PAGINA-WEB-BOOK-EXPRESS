from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserProfile",
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
                    "phone",
                    models.CharField(
                        blank=True,
                        max_length=30,
                        verbose_name="Celular",
                    ),
                ),
                (
                    "whatsapp",
                    models.CharField(
                        blank=True,
                        max_length=30,
                        verbose_name="WhatsApp",
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="book_express_profile",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Usuario",
                    ),
                ),
            ],
            options={
                "verbose_name": "Perfil de usuario",
                "verbose_name_plural": "Perfiles de usuario",
            },
        ),
    ]
