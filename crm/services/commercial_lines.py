from decimal import Decimal


SCHOOL_TEXT = "school_text"
READING_PLAN = "reading_plan"
OTHER = "other"

VALID_PROJECTION_LINES = {
    SCHOOL_TEXT,
    READING_PLAN,
}


def resolve_product_commercial_line(product):
    """
    Return the explicit commercial line stored in the catalog.

    Runtime CRM flows do not infer the line from names, areas or product
    types. Legacy products must be classified in the catalog before they can
    enter a new projection.
    """
    explicit_line = getattr(product, "commercial_line", OTHER)

    if explicit_line in VALID_PROJECTION_LINES:
        return explicit_line

    return OTHER


def green_margin_threshold(commercial_line):
    """
    Smallest unit margin that satisfies the approved strict green rule.

    Texto escolar: green when margin > S/ 20.00.
    Plan lector: green when margin > S/ 5.00.
    """
    if commercial_line == SCHOOL_TEXT:
        return Decimal("20.01")

    if commercial_line == READING_PLAN:
        return Decimal("5.01")

    return None


def commercial_line_display(value):
    if value == SCHOOL_TEXT:
        return "Texto escolar"
    if value == READING_PLAN:
        return "Plan lector"
    return "Sin clasificar"
