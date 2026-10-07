from .activities import CommercialActivityError, record_commercial_activity
from .adoptions import AdoptionError, confirm_adoption
from .dashboard import build_crm_dashboard_summary
from .history import (
    build_opportunity_commercial_history,
    build_school_commercial_history,
    record_history_event,
)
from .opportunities import (
    OpportunityTransitionError,
    create_opportunity,
    reopen_opportunity,
    transition_opportunity_stage,
)
from .planning import (
    CRMPlanningError,
    create_opportunity_event,
    create_opportunity_reminder,
    create_opportunity_task,
    create_school_event,
    create_school_reminder,
    create_school_task,
)
from .projections import (
    CommercialProjectionError,
    create_commercial_projection_revision,
    resolve_projection_price,
)
from .reports import (
    build_activity_commercial_report,
    build_advisor_commercial_report,
    build_editorial_commercial_report,
    build_opportunity_commercial_report,
    build_school_commercial_report,
)
from .report_exports import build_crm_report_workbook
from .quotations import (
    CommercialQuotationError,
    accept_commercial_quotation,
    approve_commercial_quotation_discount,
    create_commercial_quotation,
    create_commercial_quotation_from_projection,
    preview_commercial_quotation_financials,
    reopen_commercial_quotation_negotiation,
    send_commercial_quotation,
    update_commercial_quotation_from_projection,
)
from .work_items import (
    CRMWorkItemLinkError,
    link_crm_work_item,
    link_work_item_to_opportunity,
    link_work_item_to_school,
)

__all__ = [
    "AdoptionError",
    "confirm_adoption",
    "build_crm_dashboard_summary",
    "build_opportunity_commercial_history",
    "build_school_commercial_history",
    "record_history_event",
    "CommercialProjectionError",
    "create_commercial_projection_revision",
    "resolve_projection_price",
    "build_crm_report_workbook",
    "build_activity_commercial_report",
    "build_advisor_commercial_report",
    "build_editorial_commercial_report",
    "build_opportunity_commercial_report",
    "build_school_commercial_report",
    "CommercialQuotationError",
    "create_commercial_quotation",
    "create_commercial_quotation_from_projection",
    "preview_commercial_quotation_financials",
    "update_commercial_quotation_from_projection",
    "approve_commercial_quotation_discount",
    "send_commercial_quotation",
    "accept_commercial_quotation",
    "reopen_commercial_quotation_negotiation",
    "CommercialActivityError",
    "record_commercial_activity",
    "OpportunityTransitionError",
    "create_opportunity",
    "reopen_opportunity",
    "transition_opportunity_stage",
    "CRMPlanningError",
    "create_opportunity_task",
    "create_opportunity_event",
    "create_opportunity_reminder",
    "create_school_task",
    "create_school_event",
    "create_school_reminder",
    "CRMWorkItemLinkError",
    "link_crm_work_item",
    "link_work_item_to_school",
    "link_work_item_to_opportunity",
    "recalculate_active_school_profile",
    "recalculate_school_commercial_profile",
]

from .school_scoring import (
    recalculate_active_school_profile,
    recalculate_school_commercial_profile,
)
