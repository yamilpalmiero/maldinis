# Pobla home_source/away_source en los 32 partidos de eliminatoria según
# el bracket oficial FIFA 2026 (Annex C de las regulaciones del torneo).
#
# Los 32 partidos corresponden a los match numbers oficiales FIFA 73-104:
#   - R32: M73-M88 (16 partidos)
#   - R16: M89-M96 (8 partidos)
#   - QF:  M97-M100 (4 partidos)
#   - SF:  M101-M102 (2 partidos)
#   - 3P:  M103 (tercer puesto)
#   - F:   M104 (final)
#
# Se asume que los partidos de eliminatoria vienen de Football-Data.org en
# orden cronológico (M73 el primero, M104 el último), por lo que ordenar
# por match_datetime los empareja correctamente con BRACKET_SOURCES por índice.

from django.db import migrations


BRACKET_SOURCES = [
    # Dieciseisavos (M73–M88)
    ("1E", "3ABCDF"), ("1I", "3CDFGH"), ("2A", "2B"),    ("1F", "2C"),
    ("2K", "2L"),     ("1H", "2J"),     ("1D", "3BEFIJ"), ("1G", "3AEHIJ"),
    ("1C", "2F"),     ("2E", "2I"),     ("1A", "3CEFHI"), ("1L", "3EHIJK"),
    ("1J", "2H"),     ("2D", "2G"),     ("1B", "3EFGIJ"), ("1K", "3DEIJL"),
    # Octavos (M89–M96) — ganadores de R32 por parejas
    ("W73", "W74"), ("W75", "W76"), ("W77", "W78"), ("W79", "W80"),
    ("W81", "W82"), ("W83", "W84"), ("W85", "W86"), ("W87", "W88"),
    # Cuartos (M97–M100)
    ("W89", "W90"), ("W91", "W92"), ("W93", "W94"), ("W95", "W96"),
    # Semifinales (M101–M102)
    ("W97", "W98"), ("W99", "W100"),
    # Tercer puesto (M103) — perdedores de las semifinales
    ("L101", "L102"),
    # Final (M104)
    ("W101", "W102"),
]


def populate_bracket_sources(apps, schema_editor):
    Match = apps.get_model("predictions", "Match")
    knockout_stages = ["R32", "R16", "QF", "SF", "3P", "F"]
    knockout_matches = list(
        Match.objects.filter(stage__in=knockout_stages).order_by("match_datetime")
    )

    if len(knockout_matches) == 0:
        # Sin partidos de eliminatoria todavía (BD nueva sin sync). No es error.
        return

    if len(knockout_matches) != 32:
        # Cantidad inesperada. Mejor no asumir emparejamiento a ciegas.
        print(
            f"  ⚠ Se esperaban 32 partidos de eliminatoria, se encontraron "
            f"{len(knockout_matches)}. No se pueblan los sources."
        )
        return

    for match, (home_source, away_source) in zip(knockout_matches, BRACKET_SOURCES):
        if not match.home_source:
            match.home_source = home_source
        if not match.away_source:
            match.away_source = away_source
        match.save(update_fields=["home_source", "away_source"])


def reverse_populate(apps, schema_editor):
    Match = apps.get_model("predictions", "Match")
    Match.objects.filter(stage__in=["R32", "R16", "QF", "SF", "3P", "F"]).update(
        home_source="", away_source=""
    )


class Migration(migrations.Migration):

    dependencies = [
        ("predictions", "0005_match_home_source_match_away_source"),
    ]

    operations = [
        migrations.RunPython(populate_bracket_sources, reverse_populate),
    ]