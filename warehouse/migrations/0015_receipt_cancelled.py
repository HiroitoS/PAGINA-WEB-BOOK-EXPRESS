"""Permite anular borradores de recepción sin borrar auditoría ni mover stock."""
from django.db import migrations, models
from django.db.models import Q
from django.db.models.functions import Trim, Upper


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse", "0014_distribution_operation"),
    ]

    operations = [
        migrations.AlterField(
            model_name="goodsreceipt",
            name="status",
            field=models.CharField(
                max_length=12, db_index=True, default="draft",
                choices=[
                    ("draft", "Borrador"),
                    ("validated", "Validada"),
                    ("cancelled", "Anulada"),
                ],
            ),
        ),
        migrations.RemoveConstraint(
            model_name="goodsreceipt", name="wh_unique_supplier_guide",
        ),
        migrations.RemoveConstraint(
            model_name="goodsreceipt", name="wh_unique_supplier_guide_ci",
        ),
        migrations.AddConstraint(
            model_name="goodsreceipt",
            constraint=models.UniqueConstraint(
                fields=["provider", "document_type", "document_number"],
                condition=Q(document_type="guide") & ~Q(document_number="") & ~Q(status="cancelled"),
                name="wh_unique_supplier_guide",
            ),
        ),
        migrations.AddConstraint(
            model_name="goodsreceipt",
            constraint=models.UniqueConstraint(
                Upper(Trim("document_number")), "provider", "document_type",
                condition=Q(document_type="guide") & ~Q(document_number="") & ~Q(status="cancelled"),
                name="wh_unique_supplier_guide_ci",
            ),
        ),
    ]
