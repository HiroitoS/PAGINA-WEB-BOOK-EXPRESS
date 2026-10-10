from django.contrib.postgres.operations import UnaccentExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0043_commercialactivity_location"),
    ]

    operations = [
        UnaccentExtension(),
    ]
