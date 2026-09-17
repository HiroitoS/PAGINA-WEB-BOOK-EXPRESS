from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from catalog.models import Level
from crm.models import (
    Campaign,
    CommercialTeam,
    CommercialTeamMembership,
    School,
    SchoolContact,
)


User = get_user_model()


class CRMBaseModelsTests(TestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            username="crm-admin",
            password="test-password",
        )
        self.advisor = User.objects.create_user(
            username="crm-advisor",
            password="test-password",
        )

    def test_campaign_supports_more_than_one_commercial_cycle_per_year(self):
        Campaign.objects.create(
            code="ESCOLAR-2027",
            name="Campaña escolar 2027",
            year=2027,
            campaign_type=Campaign.CampaignType.SCHOOL,
            created_by=self.creator,
        )
        Campaign.objects.create(
            code="PLAN-LECTOR-2027",
            name="Plan lector 2027",
            year=2027,
            campaign_type=Campaign.CampaignType.READING_PLAN,
            created_by=self.creator,
        )

        self.assertEqual(
            Campaign.objects.filter(year=2027).count(),
            2,
        )

    def test_campaign_rejects_invalid_date_range(self):
        campaign = Campaign(
            code="ESCOLAR-2028",
            name="Campaña escolar 2028",
            year=2028,
            starts_on=date(2028, 4, 1),
            ends_on=date(2028, 3, 1),
        )

        with self.assertRaises(ValidationError):
            campaign.full_clean()

    def test_team_does_not_duplicate_same_user(self):
        team = CommercialTeam.objects.create(
            code="VENTAS-CENTRO",
            name="Equipo comercial centro",
            created_by=self.creator,
        )

        CommercialTeamMembership.objects.create(
            team=team,
            user=self.advisor,
            role=CommercialTeamMembership.Role.ADVISOR,
            created_by=self.creator,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CommercialTeamMembership.objects.create(
                    team=team,
                    user=self.advisor,
                    role=CommercialTeamMembership.Role.ADVISOR,
                    created_by=self.creator,
                )

    def test_school_can_reuse_catalog_levels_and_have_contacts(self):
        primary = Level.objects.create(name="Primaria")
        secondary = Level.objects.create(name="Secundaria")
        team = CommercialTeam.objects.create(
            code="VENTAS-HYO",
            name="Equipo comercial Huancayo",
            created_by=self.creator,
        )
        school = School.objects.create(
            name="Colegio de prueba",
            department="Junín",
            province="Huancayo",
            district="Huancayo",
            estimated_students=300,
            team=team,
            owner=self.advisor,
            created_by=self.creator,
        )
        school.levels.add(primary, secondary)

        contact = SchoolContact.objects.create(
            school=school,
            full_name="Director de prueba",
            position="Director",
            is_primary=True,
            created_by=self.creator,
        )

        self.assertEqual(school.levels.count(), 2)
        self.assertEqual(school.contacts.count(), 1)
        self.assertEqual(contact.school, school)
        self.assertEqual(school.owner, self.advisor)
        self.assertEqual(school.team, team)
