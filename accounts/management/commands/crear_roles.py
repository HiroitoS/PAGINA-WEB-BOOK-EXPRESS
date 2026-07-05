from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group


class Command(BaseCommand):
    help = "Crea los roles base para Book Express"

    def handle(self, *args, **options):
        roles = [
            "ADMINISTRADOR",
            "CATALOGO",
            "ASESOR_COMERCIAL",
            "ALMACEN",
        ]

        for rol in roles:
            grupo, creado = Group.objects.get_or_create(name=rol)

            if creado:
                self.stdout.write(self.style.SUCCESS(f"Rol creado: {rol}"))
            else:
                self.stdout.write(self.style.WARNING(f"Rol ya existía: {rol}"))

        self.stdout.write(self.style.SUCCESS("Roles base creados correctamente."))