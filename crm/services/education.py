import re
import unicodedata


LEVEL_INITIAL = "initial"
LEVEL_PRIMARY = "primary"
LEVEL_SECONDARY = "secondary"


def normalize_education_label(value):
    normalized = unicodedata.normalize(
        "NFKD",
        str(value or "").strip(),
    )
    without_accents = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    cleaned = re.sub(
        r"[^a-z0-9]+",
        " ",
        without_accents.casefold(),
    )
    return " ".join(cleaned.split())


def educational_level_key(value):
    label = normalize_education_label(value)

    if "inicial" in label:
        return LEVEL_INITIAL
    if "primaria" in label:
        return LEVEL_PRIMARY
    if "secundaria" in label:
        return LEVEL_SECONDARY

    return None


def grade_level_key(value):
    label = normalize_education_label(value)

    if "primaria" in label:
        return LEVEL_PRIMARY
    if "secundaria" in label:
        return LEVEL_SECONDARY
    if "inicial" in label:
        return LEVEL_INITIAL

    match = re.search(r"\b([345])\s+anos?\b", label)
    if match:
        return LEVEL_INITIAL

    return None


def grade_matches_level(*, grade, level):
    level_key = educational_level_key(
        getattr(level, "name", level)
    )
    grade_key = grade_level_key(
        getattr(grade, "name", grade)
    )

    return (
        level_key is not None
        and grade_key is not None
        and level_key == grade_key
    )
