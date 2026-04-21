# 1. Libreria estandar de Python
import os

# 2. Librerias de terceros
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

# 3. Imports propios del proyecto
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
    home_score = models.PositiveSmallIntegerField(null=True, blank=True)
    away_score = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, blank=True, help_text="TIMED, IN_PLAY, FINISHED, etc.")

    def __str__(self):
        home = self.home_team.name if self.home_team else "Por definir"
        away = self.away_team.name if self.away_team else "Por definir"
        return f"{home} vs {away} ({self.match_datetime:%d/%m/%Y})"

    class Meta:
        ordering = ["match_datetime"]


class Prediction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="predictions")
    match = models.ForeignKey(
        Match, on_delete=models.CASCADE, related_name="predictions"
    )
    tournament = models.ForeignKey(
        Tournament, on_delete=models.CASCADE, related_name="predictions"
    )
    home_score = models.PositiveSmallIntegerField()
    away_score = models.PositiveSmallIntegerField()
    points = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return (
            f"{self.user.username}: {self.match} - {self.home_score}/{self.away_score}"
        )

    def calculate_points(self):
        """Calcula los puntos de esta predicción comparando con el resultado real del partido."""
        match = self.match
        if match.home_score is None or match.away_score is None:
            return 0

        # Resultado exacto
        if self.home_score == match.home_score and self.away_score == match.away_score:
            return 3

        # Acertar ganador (o empate)
        pred_winner = self._winner(self.home_score, self.away_score)
        real_winner = self._winner(match.home_score, match.away_score)
        if pred_winner == real_winner:
            return 1

        return 0

    @staticmethod
    def _winner(home, away):
        if home > away:
            return "H"
        if away > home:
            return "A"
        return "D"

    class Meta:
        unique_together = ["user", "match", "tournament"]
        ordering = ["match__match_datetime"]


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


@receiver(post_save, sender=Match)
def recalculate_predictions(sender, instance, **kwargs):
    """Cuando se guarda un Match (p. ej. al meter su resultado), recalcula los points de sus predictions."""
    if instance.home_score is None or instance.away_score is None:
        return
    for prediction in instance.predictions.all():
        new_points = prediction.calculate_points()
        if prediction.points != new_points:
            Prediction.objects.filter(pk=prediction.pk).update(points=new_points)