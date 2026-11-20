"""Reglas de custodia por feria escolar.

V1: cada ubicación de feria concreta queda vinculada a un solo colegio
mientras tenga distribuciones vigentes o históricas no anuladas.
La futura feria multi-colegio requiere ubicaciones de custodia separadas.
"""
from django.core.exceptions import ValidationError

from warehouse.models import DistributionOperation, WarehouseFairEvent, WarehouseLocation


def feria_compartida_entre_colegios(destination, school_id, *, operation_id=None):
    """Detecta una posible mezcla, incluso en operaciones antiguas ya recibidas."""
    if destination.kind != WarehouseLocation.Kind.FAIR:
        return False
    if not WarehouseFairEvent.objects.filter(location_id=destination.pk).exists():
        return False
    operations = DistributionOperation.objects.filter(
        destination_id=destination.pk,
    ).exclude(status=DistributionOperation.Status.CANCELLED).exclude(
        school_id=school_id,
    )
    if operation_id is not None:
        operations = operations.exclude(pk=operation_id)
    return operations.exists()


def validar_feria_por_colegio(destination, school_id, *, operation_id=None):
    if feria_compartida_entre_colegios(
        destination, school_id, operation_id=operation_id,
    ):
        raise ValidationError(
            "Esta feria ya está vinculada a una entrega de otro colegio. "
            "Cada colegio debe utilizar su feria o depósito temporal específico. "
            "No reutilices una feria ajena para continuar el despacho."
        )
