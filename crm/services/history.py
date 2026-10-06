from crm.models import CommercialActivity


PLATFORM_WEB = "Página Web"


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
):
    return {
        "id": key,
        "category": category,
        "event_type": event_type,
        "event_type_display": event_type_display,
        "platform": PLATFORM_WEB,
        "occurred_at": occurred_at,
        "actor": actor,
        "title": title,
        "description": description,
        "metadata": metadata or {},
    }


def build_opportunity_commercial_history(
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
                },
            )
        )

    if activities_queryset is None:
        activities_queryset = (
            CommercialActivity.objects
            .filter(opportunity=opportunity)
        )

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
                },
            )
        )

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
                },
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
                },
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
                    },
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
                    },
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
                    },
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
                    },
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
                },
            )
        )

    return sorted(
        events,
        key=lambda item: (
            item["occurred_at"],
            item["id"],
        ),
        reverse=True,
    )
