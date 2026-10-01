from django.utils.text import slugify


SCHOOL_TEXT = "school_text"
READING_PLAN = "reading_plan"
OTHER = "other"

VALID_PROJECTION_LINES = {
    SCHOOL_TEXT,
    READING_PLAN,
}


def _normalized_text(value):
    return slugify(str(value or "")).lower()


def resolve_product_commercial_line(product):
    """
    Resolve the commercial line from catalog metadata.

    Positive Plan Lector signals take priority so a literary title is never
    treated as a school textbook merely because it also has level/grade data.
    Products that cannot be classified safely remain OTHER.
    """
    product_type = getattr(product, "product_type", None)
    area = getattr(product, "area", None)
    series = getattr(product, "series", None)

    signals = [
        _normalized_text(getattr(product_type, "name", "")),
        _normalized_text(getattr(product_type, "slug", "")),
        _normalized_text(getattr(area, "name", "")),
        _normalized_text(getattr(area, "slug", "")),
        _normalized_text(getattr(series, "name", "")),
        _normalized_text(getattr(series, "slug", "")),
        _normalized_text(getattr(product, "name", "")),
    ]
    joined = " ".join(filter(None, signals))

    reading_markers = (
        "plan-lector",
        "plan-de-lectura",
        "lectura-plan",
    )
    if any(marker in joined for marker in reading_markers):
        return READING_PLAN

    school_markers = (
        "texto-escolar",
        "textos-escolares",
        "proyecto-evolucion",
        "pack-proyecto",
    )
    if any(marker in joined for marker in school_markers):
        return SCHOOL_TEXT

    if (
        getattr(product, "level_id", None)
        and getattr(product, "grade_id", None)
        and getattr(product, "area_id", None)
    ):
        return SCHOOL_TEXT

    return OTHER


def commercial_line_display(value):
    if value == SCHOOL_TEXT:
        return "Texto escolar"
    if value == READING_PLAN:
        return "Plan lector"
    return "Sin clasificar"
