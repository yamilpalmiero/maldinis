# 1. Libreria estandar de Python
import os

# 2. Librerias de terceros
from django.db import models
from django.contrib.auth.models import User
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
        ROUND_OF_32 = "R32", "Octavos de final"
        ROUND_OF_16 = "R16", "Cuartos de final"
        QUARTER_FINAL = "QF", "Semifinal"
        SEMI_FINAL = "SF", "Final"
        FINAL = "F", "Gran Final"

    home_team = models.ForeignKey(
        Team, on_delete=models.PROTECT, related_name="home_matches"
    )
    away_team = models.ForeignKey(
        Team, on_delete=models.PROTECT, related_name="away_matches"
    )
    match_datetime = models.DateTimeField()
    stage = models.CharField(max_length=10, choices=Stage.choices, default=Stage.GROUP)
    group = models.CharField(max_length=1, blank=True)  # A, B, C... L — solo fase de grupos
    home_score = models.PositiveSmallIntegerField(null=True, blank=True)
    away_score = models.PositiveSmallIntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.home_team} vs {self.away_team} ({self.match_datetime:%d/%m/%Y})"

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
