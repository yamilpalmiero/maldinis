from django.contrib import admin
from .models import Tournament, TournamentMember


@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    list_display = ['name', 'created_by', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name', 'created_by__username']


@admin.register(TournamentMember)
class TournamentMemberAdmin(admin.ModelAdmin):
    list_display = ['user', 'tournament', 'role', 'joined_at']
    list_filter = ['role']
    search_fields = ['user__username', 'tournament__name']