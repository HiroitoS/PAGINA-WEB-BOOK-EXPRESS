from django.urls import include, path
from rest_framework.routers import DefaultRouter

from crm.api.views import (
    CampaignViewSet,
    CommercialTeamViewSet,
    CRMSummaryAPIView,
    OpportunityViewSet,
    PipelineViewSet,
    SchoolViewSet,
)


app_name = "crm"

router = DefaultRouter()
router.register(r"campaigns", CampaignViewSet, basename="campaign")
router.register(r"pipelines", PipelineViewSet, basename="pipeline")
router.register(r"commercial-teams", CommercialTeamViewSet, basename="commercial-team")
router.register(r"schools", SchoolViewSet, basename="school")
router.register(r"opportunities", OpportunityViewSet, basename="opportunity")

urlpatterns = [
    path("summary/", CRMSummaryAPIView.as_view(), name="summary"),
    path("", include(router.urls)),
]
