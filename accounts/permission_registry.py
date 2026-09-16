from django.contrib.auth.models import Permission
from django.db.models import Q


FUNCTIONAL_PERMISSIONS = (
    {
        "code": "catalog.view_catalog",
        "category": "Catálogo",
        "label": "Consultar catálogo",
        "description": "Permite consultar productos, editoriales y clasificaciones.",
        "requires": [],
    },
    {
        "code": "catalog.manage_catalog",
        "category": "Catálogo",
        "label": "Gestionar catálogo",
        "description": "Permite crear, editar, activar o desactivar productos y clasificaciones.",
        "requires": ["catalog.view_catalog"],
    },
    {
        "code": "catalog.view_prices",
        "category": "Catálogo",
        "label": "Consultar precios internos",
        "description": "Permite consultar la gestión interna de precios.",
        "requires": ["catalog.view_catalog"],
    },
    {
        "code": "catalog.manage_prices",
        "category": "Catálogo",
        "label": "Gestionar precios",
        "description": "Permite registrar y modificar precios por campaña o año.",
        "requires": ["catalog.view_prices"],
    },
    {
        "code": "catalog.manage_imports",
        "category": "Catálogo",
        "label": "Gestionar importaciones",
        "description": "Permite ejecutar cargas masivas de catálogo mediante Excel.",
        "requires": ["catalog.view_catalog"],
    },
    {
        "code": "inquiries.view_inquiries",
        "category": "Solicitudes",
        "label": "Consultar solicitudes",
        "description": "Permite consultar solicitudes recibidas desde la web.",
        "requires": [],
    },
    {
        "code": "inquiries.manage_inquiries",
        "category": "Solicitudes",
        "label": "Gestionar solicitudes",
        "description": "Permite atender, cambiar estados y registrar seguimiento.",
        "requires": ["inquiries.view_inquiries"],
    },
    {
        "code": "inquiries.assign_inquiries",
        "category": "Solicitudes",
        "label": "Asignar solicitudes",
        "description": "Permite asignar o reasignar responsables de solicitudes.",
        "requires": ["inquiries.view_inquiries"],
    },
    {
        "code": "workspaces.use_workspace",
        "category": "ToDo",
        "label": "Usar ToDo",
        "description": "Permite acceder a tareas, calendario y recordatorios.",
        "requires": [],
    },
    {
        "code": "workspaces.create_workspace_group",
        "category": "ToDo",
        "label": "Crear grupos de trabajo",
        "description": "Permite crear grupos de trabajo internos.",
        "requires": ["workspaces.use_workspace"],
    },
    {
        "code": "workspaces.assign_work",
        "category": "ToDo",
        "label": "Asignar trabajo",
        "description": "Permite asignar tareas, eventos y recordatorios a otros usuarios.",
        "requires": ["workspaces.use_workspace"],
    },
    {
        "code": "workspaces.supervise_workspace",
        "category": "ToDo",
        "label": "Supervisar trabajo",
        "description": "Reserva la capacidad de supervisión transversal para jefaturas.",
        "requires": ["workspaces.use_workspace"],
    },
)


FUNCTIONAL_PERMISSION_CODES = tuple(
    item["code"] for item in FUNCTIONAL_PERMISSIONS
)

_FUNCTIONAL_PERMISSION_MAP = {
    item["code"]: item for item in FUNCTIONAL_PERMISSIONS
}


def permission_code(permission):
    return (
        f"{permission.content_type.app_label}."
        f"{permission.codename}"
    )


def get_permission_metadata(code):
    return _FUNCTIONAL_PERMISSION_MAP.get(code)


def get_functional_permissions_queryset():
    query = Q()

    for code in FUNCTIONAL_PERMISSION_CODES:
        app_label, codename = code.split(".", 1)
        query |= Q(
            content_type__app_label=app_label,
            codename=codename,
        )

    return (
        Permission.objects
        .select_related("content_type")
        .filter(query)
        .distinct()
    )


def serialize_functional_permissions():
    permissions_by_code = {
        permission_code(permission): permission
        for permission in get_functional_permissions_queryset()
    }

    result = []

    for item in FUNCTIONAL_PERMISSIONS:
        permission = permissions_by_code.get(item["code"])

        if not permission:
            continue

        result.append({
            "id": permission.id,
            "code": item["code"],
            "category": item["category"],
            "label": item["label"],
            "description": item["description"],
            "requires": item["requires"],
        })

    return result
