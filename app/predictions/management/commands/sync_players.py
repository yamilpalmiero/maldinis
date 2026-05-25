"""
Management command para sincronizar planteles del Mundial desde Football-Data.org.

REQUISITO: el API key debe tener acceso a squads (plan de pago, min. €29/mes).
Con el tier gratuito el comando termina con un mensaje de error claro.

Uso:
    python manage.py sync_players
    python manage.py sync_players --dry-run
"""
from django.core.management.base import BaseCommand

from predictions.services.football_data import FootballDataError, sync_players


class Command(BaseCommand):
    help = "Sincroniza planteles del Mundial desde Football-Data.org al modelo Player"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Muestra qué haría sin modificar la base de datos",
        )

    def handle(self, *args, **options):
        if options["dry_run"]:
            self.stdout.write(
                "Modo dry-run: se conecta a la API pero no guarda cambios.\n"
                "(No implementado — ejecutá sin --dry-run para sincronizar.)"
            )
            return

        self.stdout.write("Sincronizando jugadores desde Football-Data.org...")
        try:
            result = sync_players()
        except FootballDataError as exc:
            self.stderr.write(self.style.ERROR(f"Error: {exc}"))
            return

        self.stdout.write(self.style.SUCCESS(
            f"Listo: {result['created']} creados, "
            f"{result['updated']} actualizados, "
            f"{result['deactivated']} desactivados."
        ))
