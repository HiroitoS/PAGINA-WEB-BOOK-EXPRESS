"""Protección de guías sin alterar ni eliminar recepciones históricas."""
from django.db import migrations, models
from django.db.models import Count, Q
from django.db.models.functions import Trim, Upper


def verificar_duplicados_existentes(apps, schema_editor):
    GoodsReceipt = apps.get_model("warehouse", "GoodsReceipt")
    repetidas = list(
        GoodsReceipt.objects.using(schema_editor.connection.alias)
        .filter(document_type="guide")
        .exclude(document_number="")
        .annotate(numero_normalizado=Upper(Trim("document_number")))
        .values("provider_id", "numero_normalizado")
        .annotate(cantidad=Count("id"))
        .filter(cantidad__gt=1)
        .order_by("provider_id", "numero_normalizado")[:10]
    )
    if repetidas:
        muestras = ", ".join(
            f"editorial {r['provider_id']} / guía {r['numero_normalizado']}"
            for r in repetidas
        )
        raise RuntimeError(
            "Se encontraron guías repetidas dentro de una MISMA editorial: "
            f"{muestras}. No se borraron ni alteraron datos. "
            "Audita esos registros y regularízalos expresamente antes de "
            "aplicar la restricción de unicidad. Guías iguales de distintas "
            "editoriales sí son válidas."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            verificar_duplicados_existentes,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="goodsreceipt",
            constraint=models.UniqueConstraint(
                Upper(Trim("document_number")), "provider", "document_type",
                condition=Q(document_type="guide") & ~Q(document_number=""),
                name="wh_unique_supplier_guide_ci",
            ),
        ),
    ]
