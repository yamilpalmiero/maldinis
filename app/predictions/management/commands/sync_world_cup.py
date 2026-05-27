"""Sincroniza los partidos del Mundial desde Football-Data.org.

Uso:
    python manage.py sync_world_cup
    python manage.py sync_world_cup --dry-run
"""
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime

from predictions.services.football_data import (
    FootballDataError,
    api_group_to_letter,
    api_stage_to_match_stage,
    api_tla_to_team_code,
    get_world_cup_matches,
    sync_world_cup_matches,
)


class Command(BaseCommand):
    help = "Sincroniza los partidos del Mundial 2026 desde Football-Data.org"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Muestra qué se haría sin tocar la DB.",
        )

    def handle(self, *args, **options):
        if options["dry_run"]:
            self._dry_run()
            return

        try:
            result = sync_world_cup_matches()
        except FootballDataError as e:
            self.stderr.write(self.style.ERROR(f"Error: {e}"))
            return

        self.stdout.write(self.style.SUCCESS(
            f"\n✓ Sync completado — creados: {result['created']}, "
            f"actualizados: {result['updated']}, "
            f"con cambio de score: {result['score_updated']}, "
            f"saltados: {result['skipped']}"
        ))

    def _dry_run(self):
        from predictions.models import Team

        try:
            matches = get_world_cup_matches()
        except FootballDataError as e:
            self.stderr.write(self.style.ERROR(f"Error llamando a la API: {e}"))
            return

        self.stdout.write(f"Partidos recibidos (dry-run): {len(matches)}")
        teams_by_code = {t.code: t for t in Team.objects.all()}

        for m in matches:
            utc_date = parse_datetime(m["utcDate"])
            home_code = api_tla_to_team_code(m["homeTeam"].get("tla"))
            away_code = api_tla_to_team_code(m["awayTeam"].get("tla"))
            home_team = teams_by_code.get(home_code)
            away_team = teams_by_code.get(away_code)
            stage = api_stage_to_match_stage(m["stage"])
            home_score = m["score"]["fullTime"].get("home")
            away_score = m["score"]["fullTime"].get("away")

            if (home_code and not home_team) or (away_code and not away_team):
                self.stderr.write(self.style.WARNING(
                    f"  ⚠ No se encontró equipo: {home_code} vs {away_code}"
                ))

            self.stdout.write(
                f"  [{m['id']}] {home_code or '?'} vs {away_code or '?'} "
                f"{utc_date.isoformat() if utc_date else '?'} [{stage}] {m.get('status', '')} "
                f"score={home_score}-{away_score}"
            )
