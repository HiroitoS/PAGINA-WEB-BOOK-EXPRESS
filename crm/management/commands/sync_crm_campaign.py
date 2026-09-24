from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from crm.models import Campaign


CAMPAIGN_TYPE_NAMES = {
    Campaign.CampaignType.SCHOOL: "Campaña escolar",
    Campaign.CampaignType.READING_PLAN: "Plan lector",
    Campaign.CampaignType.GENERAL: "Campaña general",
}


class Command(BaseCommand):
    help = (
        "Crea o actualiza una campaña comercial del CRM sin duplicarla "
        "para el mismo tipo y año."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--year",
            type=int,
            required=True,
            help="Año comercial de la campaña. Ejemplo: 2027.",
        )
        parser.add_argument(
            "--name",
            type=str,
            default="",
            help=(
                "Nombre visible de la campaña. Si se omite, se genera "
                "a partir del tipo y el año."
            ),
        )
        parser.add_argument(
            "--campaign-type",
            choices=[choice for choice, _label in Campaign.CampaignType.choices],
            default=Campaign.CampaignType.SCHOOL,
            help="Tipo de campaña comercial.",
        )
        parser.add_argument(
            "--status",
            choices=[choice for choice, _label in Campaign.Status.choices],
            default=Campaign.Status.PLANNING,
            help="Estado inicial de la campaña.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        year = options["year"]

        if year < 2000:
            raise CommandError("El año de campaña debe ser 2000 o superior.")

        campaign_type = options["campaign_type"]
        status = options["status"]
        supplied_name = options["name"].strip()
        base_name = CAMPAIGN_TYPE_NAMES[campaign_type]
        name = supplied_name or f"{base_name} {year}"

        code = f"{campaign_type.replace('_', '-').upper()}-{year}"

        matching_campaigns = Campaign.objects.filter(
            year=year,
            campaign_type=campaign_type,
        ).order_by("id")

        if matching_campaigns.count() > 1:
            raise CommandError(
                "Existe más de una campaña para el mismo tipo y año. "
                "Revísalas antes de sincronizar para no ocultar duplicados."
            )

        campaign = matching_campaigns.first()
        created = campaign is None

        if campaign is None:
            campaign = Campaign(
                code=code,
                year=year,
                campaign_type=campaign_type,
            )

        campaign.name = name
        campaign.year = year
        campaign.campaign_type = campaign_type
        campaign.status = status
        campaign.full_clean()

        if created:
            campaign.save()
        else:
            campaign.save(
                update_fields=[
                    "name",
                    "year",
                    "campaign_type",
                    "status",
                    "updated_at",
                ]
            )

        action = "creada" if created else "actualizada"
        self.stdout.write(
            self.style.SUCCESS(
                f"Campaña comercial {action}: {campaign.name} "
                f"[{campaign.get_status_display()}]."
            )
        )
