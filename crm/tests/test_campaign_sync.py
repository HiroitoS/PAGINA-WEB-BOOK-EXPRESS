from django.core.management import call_command
from django.test import TestCase

from crm.models import Campaign


class SyncCRMCampaignCommandTests(TestCase):
    def test_sync_creates_school_campaign_in_planning(self):
        call_command(
            "sync_crm_campaign",
            year=2027,
        )

        campaign = Campaign.objects.get(code="SCHOOL-2027")

        self.assertEqual(campaign.name, "Campaña escolar 2027")
        self.assertEqual(campaign.year, 2027)
        self.assertEqual(
            campaign.campaign_type,
            Campaign.CampaignType.SCHOOL,
        )
        self.assertEqual(
            campaign.status,
            Campaign.Status.PLANNING,
        )

    def test_sync_is_idempotent_for_same_type_and_year(self):
        call_command(
            "sync_crm_campaign",
            year=2027,
            name="Campaña escolar 2027",
            status=Campaign.Status.PLANNING,
        )

        campaign = Campaign.objects.get(code="SCHOOL-2027")
        original_id = campaign.id

        call_command(
            "sync_crm_campaign",
            year=2027,
            name="Campaña comercial escolar 2027",
            status=Campaign.Status.ACTIVE,
        )

        campaign.refresh_from_db()

        self.assertEqual(
            Campaign.objects.filter(code="SCHOOL-2027").count(),
            1,
        )
        self.assertEqual(campaign.id, original_id)
        self.assertEqual(
            campaign.name,
            "Campaña comercial escolar 2027",
        )
        self.assertEqual(
            campaign.status,
            Campaign.Status.ACTIVE,
        )


    def test_sync_reuses_existing_campaign_for_same_type_and_year(self):
        existing = Campaign.objects.create(
            code="ESCOLAR-2027-LEGACY",
            name="Campaña anterior",
            year=2027,
            campaign_type=Campaign.CampaignType.SCHOOL,
            status=Campaign.Status.PLANNING,
        )

        call_command(
            "sync_crm_campaign",
            year=2027,
            name="Campaña escolar 2027",
            status=Campaign.Status.ACTIVE,
        )

        existing.refresh_from_db()

        self.assertEqual(
            Campaign.objects.filter(
                year=2027,
                campaign_type=Campaign.CampaignType.SCHOOL,
            ).count(),
            1,
        )
        self.assertEqual(existing.code, "ESCOLAR-2027-LEGACY")
        self.assertEqual(existing.name, "Campaña escolar 2027")
        self.assertEqual(existing.status, Campaign.Status.ACTIVE)
