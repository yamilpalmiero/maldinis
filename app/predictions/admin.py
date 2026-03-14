from django.contrib import admin
from .models import Team, Match, Prediction


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'flag']
    search_fields = ['name', 'code']
    ordering = ['name']


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ['home_team', 'away_team', 'stage', 'match_datetime', 'home_score', 'away_score']
    list_filter = ['stage']
    search_fields = ['home_team__name', 'away_team__name']
    ordering = ['match_datetime']


@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = ['user', 'match', 'home_score', 'away_score', 'points']
    list_filter = ['points']
    search_fields = ['user__username']