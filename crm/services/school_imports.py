import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from django.db import transaction
from django.db.models import Max
from django.utils.text import slugify
from openpyxl import load_workbook

from catalog.models import Level
from crm.models import (
    InformationSource,
    School,
    SchoolCampus,
    SchoolEducationalService,
    SchoolImportBatch,
    SchoolImportRow,
    SchoolPopulationRecord,
)


HEADER_ALIASES = {
    "codigo_modular": "modular_code",
    "codigo_de_institucion": "institution_code",
    "codigo_institucion": "institution_code",
    "nombre_de_ie": "school_name",
    "nombre_ie": "school_name",
    "nombre_de_la_ie": "school_name",
    "nivel_modalidad": "level_name",
    "nivel": "level_name",
    "dependencia": "dependency",
    "direccion": "address",
    "direccion_de_ie": "address",
    "departamento": "department",
    "provincia": "province",
    "distrito": "district",
    "departamento_provincia_distrito": "location_combined",
    "alumnos": "students",
}

REQUIRED_COLUMNS = {
    "school_name": "Nombre de IE",
    "level_name": "Nivel/Modalidad",
    "students": "Alumnos",
}


def _normalize_header(value):
    text = str(value or "").strip().lower()
    text = "".join(
        character
        for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text


def _canonical_header(value):
    normalized = _normalize_header(value)

    if normalized in HEADER_ALIASES:
        return HEADER_ALIASES[normalized]

    if normalized.startswith("alumnos"):
        return "students"

    if normalized.startswith("direccion_de_ie"):
        return "address"

    if (
        "departamento" in normalized
        and "provincia" in normalized
        and "distrito" in normalized
    ):
        return "location_combined"

    return None


def _clean_text(value):
    if value is None:
        return ""

    if isinstance(value, float) and value.is_integer():
        return str(int(value)).strip()

    return str(value).strip()


def _clean_code(value):
    text = _clean_text(value)

    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]

    return text


def _normalize_value(value):
    text = _clean_text(value).casefold()
    text = "".join(
        character
        for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _parse_students(value):
    if value in (None, ""):
        return None

    if isinstance(value, bool):
        raise ValueError("La cantidad de alumnos debe ser numérica.")

    try:
        number = int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError) as error:
        raise ValueError(
            "La cantidad de alumnos debe ser numérica."
        ) from error

    if number < 0:
        raise ValueError(
            "La cantidad de alumnos no puede ser negativa."
        )

    return number


def _resolve_level(raw_value):
    raw_text = _clean_text(raw_value)
    normalized = _normalize_header(raw_text)

    candidates = []

    if "inicial" in normalized:
        candidates.append("inicial")
    if "primaria" in normalized:
        candidates.append("primaria")
    if "secundaria" in normalized:
        candidates.append("secundaria")

    candidates.append(slugify(raw_text))

    for slug in dict.fromkeys(candidates):
        if not slug:
            continue

        level = Level.objects.filter(
            slug__iexact=slug,
            is_active=True,
        ).first()

        if level is not None:
            return level

    return (
        Level.objects
        .filter(name__iexact=raw_text, is_active=True)
        .first()
    )


def _split_location(value):
    text = _clean_text(value)

    if not text:
        return "", "", ""

    parts = [
        part.strip()
        for part in re.split(r"\s*/\s*", text)
        if part.strip()
    ]

    if len(parts) >= 3:
        return parts[0], parts[1], " / ".join(parts[2:])

    if len(parts) == 2:
        return parts[0], parts[1], ""

    return parts[0], "", ""


def _sheet_and_columns(file_path):
    workbook = load_workbook(file_path, data_only=True)

    if "Instituciones" in workbook.sheetnames:
        sheet = workbook["Instituciones"]
    else:
        sheet = workbook.active

    columns = {}

    for index, cell in enumerate(sheet[1]):
        canonical = _canonical_header(cell.value)

        if canonical and canonical not in columns:
            columns[canonical] = index

    missing = [
        display_name
        for canonical, display_name in REQUIRED_COLUMNS.items()
        if canonical not in columns
    ]

    if missing:
        raise ValueError(
            "Faltan columnas obligatorias: "
            + ", ".join(missing)
            + "."
        )

    return sheet, columns


def _cell(row, columns, key):
    index = columns.get(key)

    if index is None or index >= len(row):
        return None

    return row[index]


def _read_rows(file_path):
    sheet, columns = _sheet_and_columns(file_path)
    rows = []

    for row_number, row in enumerate(
        sheet.iter_rows(min_row=2, values_only=True),
        start=2,
    ):
        if all(value in (None, "") for value in row):
            continue

        combined_department, combined_province, combined_district = (
            _split_location(
                _cell(row, columns, "location_combined")
            )
        )

        data = {
            "institution_code": _clean_code(
                _cell(row, columns, "institution_code")
            ),
            "modular_code": _clean_code(
                _cell(row, columns, "modular_code")
            ),
            "school_name": _clean_text(
                _cell(row, columns, "school_name")
            ),
            "level_name": _clean_text(
                _cell(row, columns, "level_name")
            ),
            "dependency": _clean_text(
                _cell(row, columns, "dependency")
            ),
            "address": _clean_text(
                _cell(row, columns, "address")
            ),
            "department": (
                _clean_text(_cell(row, columns, "department"))
                or combined_department
            ),
            "province": (
                _clean_text(_cell(row, columns, "province"))
                or combined_province
            ),
            "district": (
                _clean_text(_cell(row, columns, "district"))
                or combined_district
            ),
            "students_raw": _cell(row, columns, "students"),
        }

        rows.append((row_number, data))

    return rows


def _school_key(data):
    institution_code = _normalize_value(
        data.get("institution_code")
    )

    if institution_code:
        return f"official:{institution_code}"

    parts = [
        _normalize_value(data.get("school_name")),
        _normalize_value(data.get("department")),
        _normalize_value(data.get("province")),
    ]
    return "provisional:" + "|".join(parts)


def _campus_key(data):
    parts = [
        _normalize_value(data.get("address")),
        _normalize_value(data.get("department")),
        _normalize_value(data.get("province")),
        _normalize_value(data.get("district")),
    ]

    if not any(parts):
        return "sin-ubicacion"

    return "|".join(parts)


def _row_signature(data):
    return (
        _normalize_value(data.get("school_name")),
        _normalize_value(data.get("level_name")),
        _normalize_value(data.get("modular_code")),
        _normalize_value(data.get("dependency")),
        _normalize_value(data.get("address")),
        _normalize_value(data.get("department")),
        _normalize_value(data.get("province")),
        _normalize_value(data.get("district")),
        data.get("students"),
    )


def _campus_signature(data):
    return (
        _normalize_value(data.get("address")),
        _normalize_value(data.get("department")),
        _normalize_value(data.get("province")),
        _normalize_value(data.get("district")),
    )


def _preview_error_batch(batch, message):
    SchoolImportRow.objects.create(
        batch=batch,
        row_number=1,
        action=SchoolImportRow.Action.ERROR,
        warnings=[],
        errors=[message],
        data={},
    )
    batch.total_errors = 1
    batch.status = SchoolImportBatch.Status.ERROR
    batch.save(
        update_fields=[
            "total_errors",
            "status",
            "updated_at",
        ]
    )
    return batch


def _find_existing_school(entries):
    first = entries[0]["data"]
    institution_code = first.get("institution_code")

    if institution_code:
        return School.objects.filter(
            institution_code__iexact=institution_code
        ).first()

    school_name = first.get("school_name")
    if not school_name:
        return None

    candidates = list(
        School.objects
        .filter(
            institution_code__isnull=True,
            name__iexact=school_name,
        )
        .prefetch_related("campuses")
        .order_by("id")[:3]
    )

    if len(candidates) == 1:
        return candidates[0]

    if len(candidates) <= 1:
        return None

    imported_campus_keys = {
        entry["data"].get("campus_key")
        for entry in entries
    }

    matches = []
    for school in candidates:
        current_keys = {
            "|".join(
                [
                    _normalize_value(campus.address),
                    _normalize_value(campus.department),
                    _normalize_value(campus.province),
                    _normalize_value(campus.district),
                ]
            )
            for campus in school.campuses.all()
        }

        if imported_campus_keys & current_keys:
            matches.append(school)

    return matches[0] if len(matches) == 1 else None


def _append_error(entry, message):
    if message not in entry["errors"]:
        entry["errors"].append(message)


def _append_warning(entry, message):
    if message not in entry["warnings"]:
        entry["warnings"].append(message)


def _validate_group_duplicates(entries):
    by_campus_level = defaultdict(list)

    for entry in entries:
        if entry["errors"] or entry["level"] is None:
            continue

        data = entry["data"]
        by_campus_level[
            (data["campus_key"], entry["level"].id)
        ].append(entry)

    for bucket in by_campus_level.values():
        if len(bucket) <= 1:
            continue

        bucket.sort(key=lambda item: item["row_number"])
        canonical = bucket[0]

        for entry in bucket[1:]:
            if _row_signature(entry["data"]) == _row_signature(
                canonical["data"]
            ):
                entry["data"]["skip_import"] = True
                _append_warning(
                    entry,
                    (
                        "Registro repetido exactamente. "
                        "Se utilizará una sola vez."
                    ),
                )
                continue

        active = [
            entry
            for entry in bucket
            if not entry["data"].get("skip_import")
        ]

        if len(active) <= 1:
            continue

        modular_codes = {
            _normalize_value(
                entry["data"].get("modular_code")
            )
            for entry in active
            if entry["data"].get("modular_code")
        }
        student_counts = {
            entry["data"].get("students")
            for entry in active
            if entry["data"].get("students") is not None
        }

        if len(modular_codes) > 1:
            for entry in active:
                _append_error(
                    entry,
                    (
                        "La misma sede y nivel tienen más de un "
                        "Código modular. Revise cuál corresponde."
                    ),
                )
            continue

        if len(student_counts) > 1:
            for entry in active:
                _append_error(
                    entry,
                    (
                        "La misma sede y nivel tienen cantidades de "
                        "alumnos diferentes. Revise la población correcta."
                    ),
                )
            continue

        for entry in active[1:]:
            entry["data"]["skip_import"] = True
            _append_warning(
                entry,
                (
                    "Se encontró otro registro del mismo nivel en la "
                    "misma sede. Se conservará un solo registro."
                ),
            )


def _validate_modular_locations(entries):
    by_modular = defaultdict(list)

    for entry in entries:
        modular_code = entry["data"].get("modular_code")

        if not modular_code or entry["data"].get("skip_import"):
            continue

        by_modular[_normalize_value(modular_code)].append(entry)

    for bucket in by_modular.values():
        campus_keys = {
            entry["data"].get("campus_key")
            for entry in bucket
        }

        if len(campus_keys) <= 1:
            continue

        rows = ", ".join(
            str(entry["row_number"])
            for entry in sorted(
                bucket,
                key=lambda item: item["row_number"],
            )
        )

        for entry in bucket:
            _append_error(
                entry,
                (
                    "El mismo Código modular aparece en más de una "
                    f"sede (filas {rows}). Revise si se trata de una "
                    "sede distinta o de una dirección anterior."
                ),
            )


def _validate_modular_across_schools(groups):
    modular_groups = defaultdict(list)

    for school_key, entries in groups.items():
        for entry in entries:
            modular_code = entry["data"].get("modular_code")

            if not modular_code or entry["data"].get("skip_import"):
                continue

            modular_groups[_normalize_value(modular_code)].append(
                (school_key, entry)
            )

    for occurrences in modular_groups.values():
        school_keys = {
            school_key
            for school_key, _entry in occurrences
        }

        if len(school_keys) <= 1:
            continue

        for _school_key, entry in occurrences:
            _append_error(
                entry,
                (
                    "El Código modular aparece asociado a más de una "
                    "institución dentro del archivo."
                ),
            )


def _validate_existing_modular_codes(groups):
    modular_codes = {
        entry["data"].get("modular_code")
        for entries in groups.values()
        for entry in entries
        if entry["data"].get("modular_code")
    }

    if not modular_codes:
        return

    existing_services = (
        SchoolEducationalService.objects
        .filter(modular_code__in=modular_codes)
        .select_related("school")
    )
    existing_by_code = {
        _normalize_value(service.modular_code): service
        for service in existing_services
    }

    for entries in groups.values():
        expected_school = _find_existing_school(entries)

        for entry in entries:
            modular_code = entry["data"].get("modular_code")
            if not modular_code:
                continue

            service = existing_by_code.get(
                _normalize_value(modular_code)
            )
            if service is None:
                continue

            if (
                expected_school is not None
                and service.school_id == expected_school.id
            ):
                continue

            institution_code = entry["data"].get(
                "institution_code"
            )
            if (
                institution_code
                and service.school.institution_code
                and _normalize_value(
                    service.school.institution_code
                )
                == _normalize_value(institution_code)
            ):
                continue

            _append_error(
                entry,
                (
                    "El Código modular ya pertenece a otra "
                    "institución registrada."
                ),
            )


def create_school_import_preview(
    *,
    file,
    population_year,
    actor,
):
    batch = SchoolImportBatch.objects.create(
        file=file,
        population_year=population_year,
        created_by=actor,
        status=SchoolImportBatch.Status.PENDING,
    )

    try:
        batch.file.open("rb")
        excel_rows = _read_rows(batch.file)
    except Exception as error:
        return _preview_error_batch(batch, str(error))
    finally:
        batch.file.close()

    if not excel_rows:
        return _preview_error_batch(
            batch,
            "El archivo no contiene instituciones para importar.",
        )

    prepared_entries = []

    for row_number, data in excel_rows:
        errors = []
        warnings = []

        school_name = data["school_name"]
        level_raw = data["level_name"]

        if not school_name:
            errors.append("El Nombre de IE es obligatorio.")

        if not level_raw:
            errors.append("El Nivel/Modalidad es obligatorio.")

        if not data["institution_code"]:
            warnings.append(
                (
                    "Código de institución no registrado. "
                    "Se utilizará un código interno Book Express y "
                    "podrá completar el código oficial después."
                )
            )

        if not data["modular_code"]:
            warnings.append(
                (
                    "Código modular no registrado. Podrá completarlo "
                    "cuando cuente con el dato oficial."
                )
            )

        if not data["dependency"]:
            warnings.append("Dependencia no registrada.")

        if not data["address"]:
            warnings.append(
                (
                    "Dirección no registrada. La sede quedará pendiente "
                    "de completar."
                )
            )

        if not any(
            (
                data["department"],
                data["province"],
                data["district"],
            )
        ):
            warnings.append(
                "Ubicación geográfica no registrada."
            )

        level = _resolve_level(level_raw) if level_raw else None

        if level_raw and level is None:
            errors.append(
                (
                    f"No se reconoce el nivel '{level_raw}'. "
                    "Usa Inicial, Primaria o Secundaria."
                )
            )

        try:
            students = _parse_students(data["students_raw"])
        except ValueError as error:
            students = None
            errors.append(str(error))

        if students is None:
            errors.append(
                "La cantidad de alumnos del nivel es obligatoria."
            )

        data["students"] = students
        data.pop("students_raw", None)

        if level is not None:
            data["level_id"] = level.id
            data["level_display"] = level.name

        data["school_key"] = _school_key(data)
        data["campus_key"] = _campus_key(data)
        data["skip_import"] = False

        prepared_entries.append(
            {
                "row_number": row_number,
                "data": data,
                "level": level,
                "errors": errors,
                "warnings": warnings,
            }
        )

    groups = defaultdict(list)
    for entry in prepared_entries:
        groups[entry["data"]["school_key"]].append(entry)

    for entries in groups.values():
        _validate_group_duplicates(entries)
        _validate_modular_locations(entries)

        institution_codes = {
            _normalize_value(
                entry["data"].get("institution_code")
            )
            for entry in entries
            if entry["data"].get("institution_code")
        }
        school_names = {
            _normalize_value(entry["data"].get("school_name"))
            for entry in entries
            if entry["data"].get("school_name")
        }

        if len(institution_codes) <= 1 and len(school_names) > 1:
            for entry in entries:
                _append_warning(
                    entry,
                    (
                        "El mismo Código de institución aparece con "
                        "variaciones en el nombre del colegio. Revise "
                        "la denominación institucional."
                    ),
                )

        dependencies = {
            _normalize_value(entry["data"].get("dependency"))
            for entry in entries
            if entry["data"].get("dependency")
        }
        if len(dependencies) > 1:
            for entry in entries:
                _append_warning(
                    entry,
                    (
                        "La dependencia institucional no coincide en "
                        "todas las filas del colegio."
                    ),
                )

    _validate_modular_across_schools(groups)
    _validate_existing_modular_codes(groups)

    school_actions = {}
    total_errors = 0
    total_warnings = 0

    for school_key, entries in groups.items():
        existing_school = _find_existing_school(entries)
        group_has_errors = any(
            entry["errors"]
            for entry in entries
        )

        school_actions[school_key] = (
            SchoolImportRow.Action.UPDATE
            if existing_school is not None
            else SchoolImportRow.Action.NEW
        )

        for entry in entries:
            action = school_actions[school_key]

            if entry["errors"]:
                action = SchoolImportRow.Action.ERROR
                total_errors += 1

            if entry["warnings"]:
                total_warnings += 1

            data = entry["data"]

            SchoolImportRow.objects.create(
                batch=batch,
                row_number=entry["row_number"],
                institution_code=data["institution_code"],
                modular_code=data["modular_code"],
                school_name=data["school_name"],
                level_name=data["level_name"],
                action=action,
                warnings=entry["warnings"],
                errors=entry["errors"],
                data=data,
            )

        if group_has_errors:
            continue

    ready_actions = [
        action
        for school_key, action in school_actions.items()
        if not any(entry["errors"] for entry in groups[school_key])
    ]

    batch.total_rows = len(excel_rows)
    batch.total_schools = len(groups)
    batch.total_new = sum(
        1
        for action in ready_actions
        if action == SchoolImportRow.Action.NEW
    )
    batch.total_updated = sum(
        1
        for action in ready_actions
        if action == SchoolImportRow.Action.UPDATE
    )
    batch.total_warnings = total_warnings
    batch.total_errors = total_errors
    batch.status = (
        SchoolImportBatch.Status.VALIDATED
        if total_errors == 0
        else SchoolImportBatch.Status.ERROR
    )
    batch.save(
        update_fields=[
            "total_rows",
            "total_schools",
            "total_new",
            "total_updated",
            "total_warnings",
            "total_errors",
            "status",
            "updated_at",
        ]
    )

    return batch


def _first_non_empty(rows, field):
    for row in rows:
        value = row.data.get(field)
        if value not in (None, ""):
            return value

    return ""


def _update_school_from_rows(
    *,
    school,
    rows,
    actor,
):
    school.name = _first_non_empty(rows, "school_name") or school.name
    school.dependency = (
        _first_non_empty(rows, "dependency")
        or school.dependency
    )
    school.is_active = True

    modular_codes = {
        row.data.get("modular_code")
        for row in rows
        if (
            row.data.get("modular_code")
            and not row.data.get("skip_import")
        )
    }
    school.modular_code = (
        next(iter(modular_codes))
        if len(modular_codes) == 1
        else ""
    )

    student_values = [
        row.data.get("students")
        for row in rows
        if (
            row.data.get("students") is not None
            and not row.data.get("skip_import")
        )
    ]
    if student_values:
        school.estimated_students = sum(student_values)

    if school.created_by_id is None:
        school.created_by = actor

    school.full_clean()
    school.save()


def _next_campus_sequence(school):
    current_max = (
        school.campuses.aggregate(value=Max("sequence"))
        .get("value")
        or 0
    )
    return current_max + 1


def _find_matching_campus(school, data):
    target = _campus_signature(data)

    for campus in school.campuses.all():
        current = (
            _normalize_value(campus.address),
            _normalize_value(campus.department),
            _normalize_value(campus.province),
            _normalize_value(campus.district),
        )

        if current == target:
            return campus

    return None


def _campus_from_data(
    *,
    school,
    data,
    actor,
):
    campus = _find_matching_campus(school, data)

    if campus is None:
        sequence = _next_campus_sequence(school)
        is_main = not school.campuses.filter(is_main=True).exists()
        campus = SchoolCampus(
            school=school,
            sequence=sequence,
            name=(
                "Sede principal"
                if is_main
                else f"Sede {sequence}"
            ),
            is_main=is_main,
            created_by=actor,
        )

    campus.address = data.get("address", "")
    campus.department = data.get("department", "")
    campus.province = data.get("province", "")
    campus.district = data.get("district", "")
    campus.is_active = True
    campus.full_clean()
    campus.save()

    return campus


def _sync_school_main_location(school):
    main = (
        school.campuses
        .filter(is_main=True)
        .order_by("sequence", "id")
        .first()
    )

    if main is None:
        return

    school.address = main.address
    school.reference = main.reference
    school.department = main.department
    school.province = main.province
    school.district = main.district
    school.save(
        update_fields=[
            "address",
            "reference",
            "department",
            "province",
            "district",
            "updated_at",
        ]
    )


def _upsert_population(
    *,
    service,
    student_count,
    population_year,
    actor,
    source_detail,
):
    current = (
        service.population_records
        .filter(is_current=True)
        .order_by("-year", "-created_at")
        .first()
    )

    if current is not None and current.year == population_year:
        current.student_count = student_count
        current.source = InformationSource.IMPORT
        current.source_detail = source_detail
        current.recorded_by = actor
        current.save(
            update_fields=[
                "student_count",
                "source",
                "source_detail",
                "recorded_by",
                "updated_at",
            ]
        )
        return

    service.population_records.filter(
        is_current=True
    ).update(is_current=False)

    SchoolPopulationRecord.objects.create(
        service=service,
        year=population_year,
        student_count=student_count,
        source=InformationSource.IMPORT,
        source_detail=source_detail,
        is_current=True,
        recorded_by=actor,
    )


def _resolve_service(
    *,
    school,
    campus,
    level,
    data,
    actor,
):
    modular_code = data.get("modular_code") or None

    service = None
    if modular_code:
        service = (
            SchoolEducationalService.objects
            .filter(modular_code__iexact=modular_code)
            .first()
        )

        if service is not None and service.school_id != school.id:
            raise ValueError(
                (
                    f"El Código modular {modular_code} pertenece a "
                    "otra institución."
                )
            )

    if service is None:
        service = (
            SchoolEducationalService.objects
            .filter(
                school=school,
                campus=campus,
                level=level,
            )
            .first()
        )

    if service is None:
        service = SchoolEducationalService(
            school=school,
            campus=campus,
            level=level,
            created_by=actor,
        )

    service.campus = campus
    service.level = level
    service.modular_code = modular_code
    service.modality = data.get("level_name", "")
    service.is_active = True
    service.full_clean()
    service.save()

    return service


@transaction.atomic
def confirm_school_import(*, batch_id, actor):
    batch = (
        SchoolImportBatch.objects
        .select_for_update()
        .prefetch_related("rows")
        .get(pk=batch_id)
    )

    if batch.status == SchoolImportBatch.Status.IMPORTED:
        raise ValueError("Esta importación ya fue confirmada.")

    if batch.total_errors > 0:
        raise ValueError(
            "Corrige los errores que requieren revisión antes de confirmar."
        )

    if batch.status != SchoolImportBatch.Status.VALIDATED:
        raise ValueError(
            "La importación todavía no está lista para confirmar."
        )

    grouped_rows = defaultdict(list)

    for row in batch.rows.all():
        grouped_rows[row.data["school_key"]].append(row)

    source_detail = f"Excel {Path(batch.file.name).name}"

    for rows in grouped_rows.values():
        rows.sort(key=lambda item: item.row_number)
        import_rows = [
            row
            for row in rows
            if not row.data.get("skip_import")
        ]

        if not import_rows:
            for row in rows:
                row.processed = True
                row.save(
                    update_fields=["processed", "updated_at"]
                )
            continue

        first = import_rows[0]
        institution_code = first.institution_code or None

        school = None
        if institution_code:
            school = School.objects.filter(
                institution_code__iexact=institution_code
            ).first()
        else:
            school = _find_existing_school(
                [
                    {
                        "data": row.data,
                        "row_number": row.row_number,
                        "errors": row.errors,
                        "warnings": row.warnings,
                        "level": None,
                    }
                    for row in import_rows
                ]
            )

        if school is None:
            school = School(
                institution_code=institution_code,
                name=first.school_name,
                created_by=actor,
            )
        elif (
            institution_code
            and not school.institution_code
        ):
            school.institution_code = institution_code

        _update_school_from_rows(
            school=school,
            rows=import_rows,
            actor=actor,
        )

        campus_rows = defaultdict(list)
        for row in import_rows:
            campus_rows[row.data["campus_key"]].append(row)

        imported_levels = []

        for campus_group in campus_rows.values():
            campus_group.sort(key=lambda item: item.row_number)
            campus = _campus_from_data(
                school=school,
                data=campus_group[0].data,
                actor=actor,
            )

            for row in campus_group:
                data = row.data
                level = Level.objects.get(pk=data["level_id"])
                imported_levels.append(level)

                service = _resolve_service(
                    school=school,
                    campus=campus,
                    level=level,
                    data=data,
                    actor=actor,
                )

                _upsert_population(
                    service=service,
                    student_count=data["students"],
                    population_year=batch.population_year,
                    actor=actor,
                    source_detail=source_detail,
                )

        if imported_levels:
            school.levels.add(*imported_levels)

        _sync_school_main_location(school)

        for row in rows:
            row.processed = True
            row.save(
                update_fields=["processed", "updated_at"]
            )

    batch.status = SchoolImportBatch.Status.IMPORTED
    batch.save(
        update_fields=["status", "updated_at"]
    )

    return batch
