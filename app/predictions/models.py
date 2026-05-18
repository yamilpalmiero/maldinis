# 1. Librerías de terceros
from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

# 2. Imports propios del proyecto
from tournaments.models import Tournament


class Team(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=3, unique=True)  # Ej: ARG, BRA, FRA
    flag = models.ImageField(upload_to="flags/", blank=True, null=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]


class Match(models.Model):
    class Stage(models.TextChoices):
        GROUP = "GROUP", "Fase de grupos"
        ROUND_OF_32 = "R32", "Dieciseisavos de final"
        ROUND_OF_16 = "R16", "Octavos de final"
        QUARTER_FINAL = "QF", "Cuartos de final"
        SEMI_FINAL = "SF", "Semifinal"
        THIRD_PLACE = "3P", "Tercer puesto"
        FINAL = "F", "Final"

    external_id = models.IntegerField(unique=True, null=True, blank=True, help_text="ID del partido en Football-Data.org")
    home_team = models.ForeignKey(
        Team, on_delete=models.PROTECT, related_name="home_matches",
        null=True, blank=True,
    )
    away_team = models.ForeignKey(
        Team, on_delete=models.PROTECT, related_name="away_matches",
        null=True, blank=True,
    )
    match_datetime = models.DateTimeField()
    stage = models.CharField(max_length=10, choices=Stage.choices, default=Stage.GROUP)
    group = models.CharField(max_length=1, blank=True)
    # Origen del slot en partidos de eliminatoria.
    # Formatos: "1A" (ganador grupo A), "2B" (2º grupo B), "3ABCDF" (3º de alguno de esos grupos),
    # "W73" (ganador M73), "L101" (perdedor M101). Vacío en fase de grupos.
    home_source = models.CharField(max_length=50, blank=True)
    away_source = models.CharField(max_length=50, blank=True)
    home_score = models.PositiveSmallIntegerField(null=True, blank=True)
    away_score = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, blank=True, help_text="TIMED, IN_PLAY, FINISHED, etc.")

    def __str__(self):
        home = self.home_team.name if self.home_team else "Por definir"
        away = self.away_team.name if self.away_team else "Por definir"
        return f"{home} vs {away} ({self.match_datetime:%d/%m/%Y})"

    class Meta:
        ordering = ["match_datetime"]


GROUP_CHOICES = [(g, g) for g in "ABCDEFGHIJKL"]


class GroupPrediction(models.Model):
    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name="group_predictions")
    tournament  = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="group_predictions")
    group       = models.CharField(max_length=1, choices=GROUP_CHOICES)
    first_team  = models.ForeignKey(Team, on_delete=models.PROTECT, related_name="predicted_first",  null=True, blank=True)
    second_team = models.ForeignKey(Team, on_delete=models.PROTECT, related_name="predicted_second", null=True, blank=True)
    third_team  = models.ForeignKey(Team, on_delete=models.PROTECT, related_name="predicted_third",  null=True, blank=True)

    class Meta:
        unique_together = ["user", "tournament", "group"]

    def __str__(self):
        return f"{self.user.username} — Grupo {self.group} ({self.tournament.name})"

    def clean(self):
        from django.db.models import Q
        teams = [t for t in [self.first_team, self.second_team, self.third_team] if t is not None]
        if len(teams) != len({t.pk for t in teams}):
            raise ValidationError("Los 3 equipos deben ser distintos.")
        valid_pks = set(
            Team.objects.filter(
                Q(home_matches__stage=Match.Stage.GROUP, home_matches__group=self.group) |
                Q(away_matches__stage=Match.Stage.GROUP, away_matches__group=self.group)
            ).values_list("pk", flat=True)
        )
        for team in teams:
            if team.pk not in valid_pks:
                raise ValidationError(f"{team} no pertenece al grupo {self.group}.")


class ThirdPlaceRanking(models.Model):
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name="third_place_rankings")
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="third_place_rankings")

    class Meta:
        unique_together = ["user", "tournament"]

    def __str__(self):
        return f"{self.user.username} — Ranking terceros ({self.tournament.name})"


class ThirdPlaceRankingEntry(models.Model):
    ranking  = models.ForeignKey(ThirdPlaceRanking, on_delete=models.CASCADE, related_name="entries")
    team     = models.ForeignKey(Team, on_delete=models.PROTECT, related_name="third_place_entries")
    position = models.PositiveSmallIntegerField()  # 1–8

    class Meta:
        unique_together = [
            ["ranking", "team"],
            ["ranking", "position"],
        ]

    def __str__(self):
        return f"{self.ranking} — #{self.position} {self.team}"

    def clean(self):
        if not (1 <= self.position <= 8):
            raise ValidationError("La posición debe estar entre 1 y 8.")


class BracketPrediction(models.Model):
    user             = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bracket_predictions")
    tournament       = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="bracket_predictions")
    match            = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="bracket_predictions")
    predicted_winner = models.ForeignKey(Team, on_delete=models.PROTECT, related_name="bracket_wins")

    class Meta:
        unique_together = ["user", "tournament", "match"]

    def __str__(self):
        return f"{self.user.username}: {self.match} → {self.predicted_winner} ({self.tournament.name})"

    def clean(self):
        if self.match.stage == Match.Stage.GROUP:
            raise ValidationError("Solo se predicen ganadores en partidos de eliminatoria.")


class SpecialPrediction(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="special_predictions"
    )
    tournament = models.ForeignKey(
        Tournament, on_delete=models.CASCADE, related_name="special_predictions"
    )
    golden_ball = models.CharField(
        max_length=100, blank=True
    )  # Balón de Oro — nombre del jugador
    golden_boot = models.CharField(
        max_length=100, blank=True
    )  # Bota de Oro — nombre del jugador

    def __str__(self):
        return f"{self.user.username} — {self.tournament.name}"

    class Meta:
        unique_together = ["user", "tournament"]
