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
    Resolve the commercial line from the explicit catalog classification.

    Metadata inference is kept only as a safe fallback for legacy products.
    Positive Plan Lector signals always take priority.
    """
    explicit_line = getattr(product, "commercial_line", OTHER)

    if explicit_line in VALID_PROJECTION_LINES:
        return explicit_line

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

    if "pack" in _normalized_text(getattr(product, "name", "")):
        return SCHOOL_TEXT

    return OTHER


def commercial_line_display(value):
    if value == SCHOOL_TEXT:
        return "Texto escolar"
    if value == READING_PLAN:
        return "Plan lector"
    return "Sin clasificar"
