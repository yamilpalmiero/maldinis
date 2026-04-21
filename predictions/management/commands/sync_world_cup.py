"""Sincroniza los partidos del Mundial desde Football-Data.org.

Uso:
    python manage.py sync_world_cup
"""
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime

from predictions.models import Match, Team, Prediction
from predictions.services.football_data import (
    get_world_cup_matches,
    api_tla_to_team_code,
    api_stage_to_match_stage,
    api_group_to_letter,
    FootballDataError,
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
        dry_run = options["dry_run"]

        try:
            matches = get_world_cup_matches()
        except FootballDataError as e:
            self.stderr.write(self.style.ERROR(f"Error llamando a la API: {e}"))
            return

        self.stdout.write(f"Partidos recibidos: {len(matches)}")

        # Cache de teams por code para no golpear la DB en cada iteración
        teams_by_code = {t.code: t for t in Team.objects.all()}

        created = 0
        updated = 0
        score_updated = 0
        skipped = 0

        for m in matches:
            external_id = m["id"]
            utc_date = parse_datetime(m["utcDate"])
            home_tla = m["homeTeam"].get("tla")
            away_tla = m["awayTeam"].get("tla")

            home_code = api_tla_to_team_code(home_tla)
            away_code = api_tla_to_team_code(away_tla)

            home_team = teams_by_code.get(home_code) if home_code else None
            away_team = teams_by_code.get(away_code) if away_code else None

            # Si un TLA está presente pero no existe en nuestra DB, avisamos
            if home_tla and not home_team:
                self.stderr.write(self.style.WARNING(
                    f"  ⚠ No se encontró Team con code={home_code} (API TLA {home_tla})"
                ))
            if away_tla and not away_team:
                self.stderr.write(self.style.WARNING(
                    f"  ⚠ No se encontró Team con code={away_code} (API TLA {away_tla})"
                ))

            stage = api_stage_to_match_stage(m["stage"])
            group = api_group_to_letter(m.get("group"))
            status = m.get("status", "")
            home_score = m["score"]["fullTime"].get("home")
            away_score = m["score"]["fullTime"].get("away")

            if dry_run:
                self.stdout.write(
                    f"  [{external_id}] {home_code or '?'} vs {away_code or '?'} "
                    f"{utc_date.isoformat() if utc_date else '?'} [{stage}] {status} "
                    f"score={home_score}-{away_score}"
                )
                continue

            defaults = {
                "home_team": home_team,
                "away_team": away_team,
                "match_datetime": utc_date,
                "stage": stage,
                "group": group,
                "home_score": home_score,
                "away_score": away_score,
                "status": status,
            }

            existing = Match.objects.filter(external_id=external_id).first()

            if existing is None:
                # Intentar emparejar con un Match existente por (fecha + equipos) antes de crear uno nuevo
                # Esto cubre los 72 partidos ya cargados por fixture que todavía no tienen external_id
                candidate = Match.objects.filter(
                    match_datetime=utc_date,
                    home_team=home_team,
                    away_team=away_team,
                    external_id__isnull=True,
                ).first()
                if candidate:
                    for k, v in defaults.items():
                        setattr(candidate, k, v)
                    candidate.external_id = external_id
                    candidate.save()
                    updated += 1
                    if home_score is not None:
                        score_updated += 1
                else:
                    # No existe: lo creamos (típicamente partidos de eliminatoria)
                    Match.objects.create(external_id=external_id, **defaults)
                    created += 1
            else:
                # Ya existe: solo actualizar si algo cambió
                changed = False
                score_changed = False
                for k, v in defaults.items():
                    if getattr(existing, k) != v:
                        setattr(existing, k, v)
                        changed = True
                        if k in ("home_score", "away_score"):
                            score_changed = True
                if changed:
                    existing.save()
                    updated += 1
                    if score_changed:
                        score_updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"\n✓ Sync completado — creados: {created}, actualizados: {updated}, "
            f"con cambio de score: {score_updated}, saltados: {skipped}"
        ))