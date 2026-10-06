from django.db import IntegrityError

from crm.models import (
    CRMHistoryEvent,
    CommercialActivity,
    Opportunity,
)


PLATFORM_WEB = "Página Web"

EVENT_TYPE_LABELS = {
    "school_created": "Colegio registrado",
    "contact_created": "Contacto registrado",
    "contact_updated": "Contacto actualizado",
    "created": "Creación",
    "stage_change": "Cambio de etapa",
    "reopened": "Reapertura",
    "projection_created": "Proyección",
    "quotation_created": "Cotización",
    "discount_approved": "Aprobación comercial",
    "quotation_sent": "Cotización enviada",
    "quotation_accepted": "Cotización aceptada",
    "quotation_reopened": "Negociación reabierta",
    "adoption_confirmed": "Adopción confirmada",
    "population_updated": "Población actualizada",
    "assignment_updated": "Asignación comercial",
    "evidence_added": "Evidencia agregada",
}


def _event(
    *,
    key,
    category,
    event_type,
    event_type_display,
    occurred_at,
    actor,
    title,
    description="",
    metadata=None,
    source_type="",
    source_id=None,
    platform=PLATFORM_WEB,
):
    return {
        "id": key,
        "category": category,
        "event_type": event_type,
        "event_type_display": event_type_display,
        "platform": platform,
        "occurred_at": occurred_at,
        "actor": actor,
        "title": title,
        "description": description,
        "metadata": metadata or {},
        "source_type": source_type,
        "source_id": source_id,
    }


def _event_signature(event):
    source_type = event.get("source_type") or ""
    source_id = event.get("source_id")

    if source_type and source_id is not None:
        return (
            source_type,
            int(source_id),
            event.get("event_type") or "",
        )

    return None


def _sort_events(events):
    return sorted(
        events,
        key=lambda item: (
            item["occurred_at"],
            str(item["id"]),
        ),
        reverse=True,
    )


def _merge_events(*event_groups):
    merged = []
    seen = set()

    for events in event_groups:
        for event in events:
            signature = _event_signature(event)

            if signature is not None and signature in seen:
                continue

            if signature is not None:
                seen.add(signature)

            merged.append(event)

    return _sort_events(merged)


def _persisted_events(queryset):
    events = []

    for item in queryset.select_related(
        "actor",
        "actor__book_express_profile",
    ):
        events.append(
            _event(
                key=f"history-{item.id}",
                category=item.category,
                event_type=item.event_type,
                event_type_display=EVENT_TYPE_LABELS.get(
                    item.event_type,
                    item.event_type.replace("_", " ").capitalize(),
                ),
                occurred_at=item.occurred_at,
                actor=item.actor,
                title=item.title,
                description=item.description,
                metadata=item.metadata,
                source_type=item.source_type,
                source_id=item.source_id,
                platform=item.platform,
            )
        )

    return events


def record_history_event(
    *,
    school,
    category,
    event_type,
    title,
    actor=None,
    opportunity=None,
    contact=None,
    description="",
    source_type="",
    source_id=None,
    metadata=None,
    occurred_at=None,
    platform=PLATFORM_WEB,
):
    values = {
        "school": school,
        "opportunity": opportunity,
        "contact": contact,
        "actor": actor,
        "category": category,
        "event_type": event_type,
        "title": title,
        "description": description or "",
        "platform": platform,
        "metadata": metadata or {},
    }

    if occurred_at is not None:
        values["occurred_at"] = occurred_at

    if source_type and source_id is not None:
        try:
            event, _ = CRMHistoryEvent.objects.get_or_create(
                source_type=source_type,
                source_id=source_id,
                event_type=event_type,
                defaults=values,
            )
            return event
        except IntegrityError:
            return CRMHistoryEvent.objects.get(
                source_type=source_type,
                source_id=source_id,
                event_type=event_type,
            )

    return CRMHistoryEvent.objects.create(
        source_type=source_type,
        source_id=source_id,
        **values,
    )


def _activity_events(activities_queryset):
    events = []

    activities = (
        activities_queryset
        .select_related(
            "performed_by",
            "performed_by__book_express_profile",
            "contact",
        )
        .order_by("occurred_at", "id")
    )

    for activity in activities:
        contact_name = (
            activity.contact.full_name
            if activity.contact_id
            else ""
        )
        description_parts = [activity.result]

        if contact_name:
            description_parts.append(
                f"Contacto: {contact_name}."
            )

        events.append(
            _event(
                key=f"activity-{activity.id}",
                category="activity",
                event_type=activity.activity_type,
                event_type_display=activity.get_activity_type_display(),
                occurred_at=activity.occurred_at,
                actor=activity.performed_by or activity.created_by,
                title=activity.summary,
                description=" ".join(
                    part.strip()
                    for part in description_parts
                    if part and part.strip()
                ),
                metadata={
                    "activity_id": activity.id,
                    "contact_id": activity.contact_id,
                    "opportunity_id": activity.opportunity_id,
                },
                source_type="commercial_activity",
                source_id=activity.id,
            )
        )

    return events


def _opportunity_legacy_events(
    *,
    opportunity,
    activities_queryset=None,
):
    events = []

    stage_history = (
        opportunity.stage_history
        .select_related(
            "from_stage",
            "to_stage",
            "changed_by",
            "changed_by__book_express_profile",
        )
        .order_by("created_at", "id")
    )

    for item in stage_history:
        if item.from_stage_id:
            title = (
                f"{item.from_stage.name} → {item.to_stage.name}"
            )
        else:
            title = f"Oportunidad creada en {item.to_stage.name}"

        events.append(
            _event(
                key=f"stage-{item.id}",
                category="opportunity",
                event_type=item.transition_type,
                event_type_display=item.get_transition_type_display(),
                occurred_at=item.created_at,
                actor=item.changed_by,
                title=title,
                description=item.note or "",
                metadata={
                    "from_stage": (
                        item.from_stage.name
                        if item.from_stage_id
                        else ""
                    ),
                    "to_stage": item.to_stage.name,
                    "opportunity_id": opportunity.id,
                },
                source_type="opportunity_stage_history",
                source_id=item.id,
            )
        )

    if activities_queryset is None:
        activities_queryset = CommercialActivity.objects.filter(
            opportunity=opportunity,
        )

    events.extend(_activity_events(activities_queryset))

    projections = (
        opportunity.projections
        .select_related(
            "created_by",
            "created_by__book_express_profile",
        )
        .order_by("created_at", "id")
    )

    for projection in projections:
        events.append(
            _event(
                key=f"projection-{projection.id}",
                category="projection",
                event_type="projection_created",
                event_type_display="Proyección",
                occurred_at=projection.created_at,
                actor=projection.created_by,
                title=f"Proyección v{projection.version} guardada",
                description=(
                    "Línea comercial: "
                    f"{projection.get_commercial_line_display()}."
                ),
                metadata={
                    "projection_id": projection.id,
                    "version": projection.version,
                    "commercial_line": projection.commercial_line,
                    "opportunity_id": opportunity.id,
                },
                source_type="commercial_projection",
                source_id=projection.id,
            )
        )

    quotations = (
        opportunity.quotations
        .select_related(
            "source_projection",
            "created_by",
            "created_by__book_express_profile",
            "discount_approved_by",
            "discount_approved_by__book_express_profile",
            "sent_by",
            "sent_by__book_express_profile",
            "accepted_by",
            "accepted_by__book_express_profile",
            "reopened_by",
            "reopened_by__book_express_profile",
        )
        .order_by("created_at", "id")
    )

    for quotation in quotations:
        source_projection = (
            f" desde Proyección v{quotation.source_projection.version}"
            if quotation.source_projection_id
            else ""
        )

        events.append(
            _event(
                key=f"quotation-{quotation.id}-created",
                category="quotation",
                event_type="quotation_created",
                event_type_display="Cotización",
                occurred_at=quotation.created_at,
                actor=quotation.created_by,
                title=f"Cotización v{quotation.version} generada",
                description=(
                    f"Se generó la cotización{source_projection}."
                ),
                metadata={
                    "quotation_id": quotation.id,
                    "version": quotation.version,
                    "status": quotation.status,
                    "opportunity_id": opportunity.id,
                },
                source_type="commercial_quotation",
                source_id=quotation.id,
            )
        )

        if quotation.discount_approved_at:
            events.append(
                _event(
                    key=f"quotation-{quotation.id}-discount-approved",
                    category="quotation",
                    event_type="discount_approved",
                    event_type_display="Aprobación comercial",
                    occurred_at=quotation.discount_approved_at,
                    actor=quotation.discount_approved_by,
                    title=(
                        f"Descuento de Cotización v"
                        f"{quotation.version} aprobado"
                    ),
                    description=quotation.discount_approval_note or "",
                    metadata={
                        "quotation_id": quotation.id,
                        "version": quotation.version,
                        "opportunity_id": opportunity.id,
                    },
                    source_type="commercial_quotation",
                    source_id=quotation.id,
                )
            )

        if quotation.sent_at:
            events.append(
                _event(
                    key=f"quotation-{quotation.id}-sent",
                    category="quotation",
                    event_type="quotation_sent",
                    event_type_display="Cotización enviada",
                    occurred_at=quotation.sent_at,
                    actor=quotation.sent_by,
                    title=f"Cotización v{quotation.version} enviada",
                    description=(
                        "La cotización fue marcada como enviada "
                        "al colegio."
                    ),
                    metadata={
                        "quotation_id": quotation.id,
                        "version": quotation.version,
                        "opportunity_id": opportunity.id,
                    },
                    source_type="commercial_quotation",
                    source_id=quotation.id,
                )
            )

        if quotation.accepted_at:
            events.append(
                _event(
                    key=f"quotation-{quotation.id}-accepted",
                    category="quotation",
                    event_type="quotation_accepted",
                    event_type_display="Cotización aceptada",
                    occurred_at=quotation.accepted_at,
                    actor=quotation.accepted_by,
                    title=f"Cotización v{quotation.version} aceptada",
                    description=(
                        "Se registró la aceptación comercial "
                        "del colegio."
                    ),
                    metadata={
                        "quotation_id": quotation.id,
                        "version": quotation.version,
                        "opportunity_id": opportunity.id,
                    },
                    source_type="commercial_quotation",
                    source_id=quotation.id,
                )
            )

        if quotation.reopened_at:
            events.append(
                _event(
                    key=f"quotation-{quotation.id}-reopened",
                    category="quotation",
                    event_type="quotation_reopened",
                    event_type_display="Negociación reabierta",
                    occurred_at=quotation.reopened_at,
                    actor=quotation.reopened_by,
                    title=(
                        f"Negociación de Cotización v"
                        f"{quotation.version} reabierta"
                    ),
                    description=quotation.reopen_reason or "",
                    metadata={
                        "quotation_id": quotation.id,
                        "version": quotation.version,
                        "opportunity_id": opportunity.id,
                    },
                    source_type="commercial_quotation",
                    source_id=quotation.id,
                )
            )

    adoptions = (
        opportunity.adoptions
        .select_related(
            "confirmed_by",
            "confirmed_by__book_express_profile",
            "authorized_contact",
            "quotation",
        )
        .order_by("confirmed_at", "id")
    )

    for adoption in adoptions:
        description = (
            f"Directivo: "
            f"{adoption.authorized_contact_name_snapshot}."
        )

        if adoption.notes:
            description = f"{description} {adoption.notes.strip()}"

        events.append(
            _event(
                key=f"adoption-{adoption.id}",
                category="adoption",
                event_type="adoption_confirmed",
                event_type_display="Adopción confirmada",
                occurred_at=adoption.confirmed_at or adoption.created_at,
                actor=adoption.confirmed_by,
                title=f"Adopción v{adoption.version} confirmada",
                description=description,
                metadata={
                    "adoption_id": adoption.id,
                    "version": adoption.version,
                    "quotation_id": adoption.quotation_id,
                    "opportunity_id": opportunity.id,
                },
                source_type="adoption",
                source_id=adoption.id,
            )
        )

    return events


def build_opportunity_commercial_history(
    *,
    opportunity,
    activities_queryset=None,
    events_queryset=None,
):
    if events_queryset is None:
        events_queryset = CRMHistoryEvent.objects.filter(
            opportunity=opportunity,
        )

    persisted = _persisted_events(events_queryset)
    legacy = _opportunity_legacy_events(
        opportunity=opportunity,
        activities_queryset=activities_queryset,
    )

    return _merge_events(persisted, legacy)


def build_school_commercial_history(
    *,
    school,
    opportunities_queryset=None,
    activities_queryset=None,
    contacts_queryset=None,
    events_queryset=None,
):
    if opportunities_queryset is None:
        opportunities_queryset = Opportunity.objects.filter(
            school=school,
        )

    if activities_queryset is None:
        activities_queryset = CommercialActivity.objects.filter(
            school=school,
        )

    if contacts_queryset is None:
        contacts_queryset = school.contacts.all()

    if events_queryset is None:
        events_queryset = CRMHistoryEvent.objects.filter(
            school=school,
        )

    persisted = _persisted_events(events_queryset)
    legacy = [
        _event(
            key=f"school-{school.id}",
            category="school",
            event_type="school_created",
            event_type_display="Colegio registrado",
            occurred_at=school.created_at,
            actor=school.created_by,
            title="Colegio incorporado a la cartera CRM",
            description=school.name,
            metadata={"school_id": school.id},
            source_type="school",
            source_id=school.id,
        )
    ]

    contacts = contacts_queryset.select_related(
        "created_by",
        "created_by__book_express_profile",
    ).order_by("created_at", "id")

    for contact in contacts:
        legacy.append(
            _event(
                key=f"contact-{contact.id}",
                category="contact",
                event_type="contact_created",
                event_type_display="Contacto registrado",
                occurred_at=contact.created_at,
                actor=contact.created_by,
                title=f"Contacto registrado: {contact.full_name}",
                description=contact.position or "",
                metadata={
                    "contact_id": contact.id,
                    "is_primary": contact.is_primary,
                },
                source_type="school_contact",
                source_id=contact.id,
            )
        )

    legacy.extend(_activity_events(activities_queryset))

    opportunities = opportunities_queryset.select_related(
        "campaign",
        "pipeline",
        "stage",
    ).order_by("created_at", "id")

    for opportunity in opportunities:
        opportunity_activities = activities_queryset.filter(
            opportunity=opportunity,
        )

        legacy.extend(
            _opportunity_legacy_events(
                opportunity=opportunity,
                activities_queryset=opportunity_activities,
            )
        )

    return _merge_events(persisted, legacy)
