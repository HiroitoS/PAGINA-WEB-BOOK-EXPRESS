from django.urls import include, path
from rest_framework.routers import DefaultRouter

from crm.api.views import (
    CampaignViewSet,
    CommercialTeamViewSet,
    CRMActivityReportAPIView,
    CRMCommercialReportAPIView,
    CRMEditorialReportAPIView,
    CRMOpportunityReportAPIView,
    CRMReportExportAPIView,
    CRMSchoolReportAPIView,
    CRMSummaryAPIView,
    OpportunityViewSet,
    PipelineViewSet,
    SchoolViewSet,
    SchoolImportViewSet,
    SchoolContactViewSet,
    MarketEditorialViewSet,
)


app_name = "crm"

router = DefaultRouter()
router.register(r"campaigns", CampaignViewSet, basename="campaign")
router.register(r"pipelines", PipelineViewSet, basename="pipeline")
router.register(r"commercial-teams", CommercialTeamViewSet, basename="commercial-team")
router.register(
    r"editorials",
    MarketEditorialViewSet,
    basename="market-editorial",
)
router.register(r"schools", SchoolViewSet, basename="school")
router.register(
    r"school-imports",
    SchoolImportViewSet,
    basename="school-import",
)
router.register(r"contacts", SchoolContactViewSet, basename="contact")
router.register(r"opportunities", OpportunityViewSet, basename="opportunity")

urlpatterns = [
    path("summary/", CRMSummaryAPIView.as_view(), name="summary"),
    path(
        "reports/commercial/",
        CRMCommercialReportAPIView.as_view(),
        name="commercial-report",
    ),
    path(
        "reports/activities/",
        CRMActivityReportAPIView.as_view(),
        name="activity-report",
    ),
    path(
        "reports/editorials/",
        CRMEditorialReportAPIView.as_view(),
        name="editorial-report",
    ),
    path(
        "reports/schools/",
        CRMSchoolReportAPIView.as_view(),
        name="school-report",
    ),
    path(
        "reports/opportunities/",
        CRMOpportunityReportAPIView.as_view(),
        name="opportunity-report",
    ),
    path(
        "reports/export/",
        CRMReportExportAPIView.as_view(),
        name="report-export",
    ),
    path("", include(router.urls)),
]
