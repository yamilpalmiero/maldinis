# 1. Librerias de terceros
from django.db import models
from django.contrib.auth.models import User


class Tournament(models.Model):
    name = models.CharField(max_length=100)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='created_tournaments')
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']


class TournamentMember(models.Model):
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Administrador'
        MEMBER = 'MEMBER', 'Miembro'

    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tournament_memberships')
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.tournament.name} ({self.role})"

    class Meta:
        unique_together = ['tournament', 'user']
        ordering = ['joined_at']