from django.contrib import admin
from .models import Team, Match, GroupPrediction, ThirdPlaceRanking, ThirdPlaceRankingEntry, BracketPrediction, SpecialPrediction


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'flag']
    search_fields = ['name', 'code']
    ordering = ['name']


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ['home_team', 'away_team', 'stage', 'match_datetime', 'home_score', 'away_score']
    list_editable = ['home_score', 'away_score']
    list_filter = ['stage']
    search_fields = ['home_team__name', 'away_team__name']
    ordering = ['match_datetime']


@admin.register(GroupPrediction)
class GroupPredictionAdmin(admin.ModelAdmin):
    list_display = ['user', 'tournament', 'group', 'first_team', 'second_team', 'third_team']
    list_filter = ['tournament', 'group']
    search_fields = ['user__username']
    ordering = ['tournament', 'group', 'user']


@admin.register(ThirdPlaceRanking)
class ThirdPlaceRankingAdmin(admin.ModelAdmin):
    list_display = ['user', 'tournament']
    list_filter = ['tournament']
    search_fields = ['user__username']


@admin.register(ThirdPlaceRankingEntry)
class ThirdPlaceRankingEntryAdmin(admin.ModelAdmin):
    list_display = ['ranking', 'position', 'team']
    list_filter = ['ranking__tournament']
    ordering = ['ranking', 'position']


@admin.register(BracketPrediction)
class BracketPredictionAdmin(admin.ModelAdmin):
    list_display = ['user', 'tournament', 'match', 'predicted_winner']
    list_filter = ['tournament', 'match__stage']
    search_fields = ['user__username']
    ordering = ['tournament', 'match__match_datetime']


@admin.register(SpecialPrediction)
class SpecialPredictionAdmin(admin.ModelAdmin):
    list_display = ['user', 'tournament', 'golden_ball', 'golden_boot']
    list_filter = ['tournament']
    search_fields = ['user__username', 'golden_ball', 'golden_boot']
