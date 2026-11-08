"""Contexto comercial legible de tareas, eventos y recordatorios.

La relación CRMWorkItemLink conserva el colegio real: no se deduce
el colegio del título editable por el usuario. Se puede usar con
prefetch_related("crm_links__school") para evitar consultas por fila.
"""


def get_crm_school(item):
    """Devuelve (school_id, school_name), o (None, '') sin vínculo CRM."""
    link = next(iter(item.crm_links.all()), None)
    if link is None and getattr(item, "task_id", None):
        link = next(iter(item.task.crm_links.all()), None)
    if link is None:
        return None, ""
    return link.school_id, link.school.name
