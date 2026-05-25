"""
Cliente para Football-Data.org API v4.

Nota sobre squads/jugadores:
  Los endpoints de squad (/competitions/WC/teams con squad incluido) requieren
  un plan de pago en Football-Data.org (mínimo "Free + Deep Data", €29/mes).
  El tier gratuito (Tier 1) devuelve 403 en esos endpoints.
  Ver https://www.football-data.org/pricing

  Mientras no se suba el tier, los jugadores se cargan manualmente desde el
  Django admin (ve a /admin/predictions/player/).  La función sync_players()
  está lista para ejecutarse una vez que el API key tenga acceso.
"""
import os
from datetime import date

import requests


BASE_URL = "https://api.football-data.org/v4"
COMPETITION_CODE = "WC"  # FIFA World Cup

# Mapeo de códigos de la API a códigos del modelo Team.code
# Solo se lista lo que difiere; si no está aquí, se usa tal cual.
TLA_OVERRIDES = {
    "CUR": "CUW",  # Curazao: API usa CUR, nosotros CUW
}

# Mapeo de stage de la API a Match.Stage
STAGE_MAP = {
    "GROUP_STAGE": "GROUP",
    "LAST_32": "R32",
    "LAST_16": "R16",
    "QUARTER_FINALS": "QF",
    "SEMI_FINALS": "SF",
    "THIRD_PLACE": "3P",
    "FINAL": "F",
}


class FootballDataError(Exception):
    pass


def _get_api_key():
    key = os.environ.get("FOOTBALL_DATA_API_KEY")
    if not key:
        raise FootballDataError("FOOTBALL_DATA_API_KEY no está definida en el entorno.")
    return key


def get_world_cup_matches():
    """Devuelve la lista de partidos del Mundial desde Football-Data.org."""
    url = f"{BASE_URL}/competitions/{COMPETITION_CODE}/matches"
    headers = {"X-Auth-Token": _get_api_key()}
    response = requests.get(url, headers=headers, timeout=15)

    if response.status_code == 429:
        raise FootballDataError("Rate limit alcanzado. Esperá unos minutos.")
    if response.status_code != 200:
        raise FootballDataError(f"API devolvió status {response.status_code}: {response.text}")

    return response.json().get("matches", [])


def api_tla_to_team_code(tla):
    """Mapea un TLA de la API al code correspondiente en nuestro modelo Team."""
    if tla is None:
        return None
    return TLA_OVERRIDES.get(tla, tla)


def api_stage_to_match_stage(stage):
    """Mapea un stage de la API al valor de Match.Stage."""
    return STAGE_MAP.get(stage, "GROUP")


def api_group_to_letter(group):
    """Convierte 'GROUP_A' en 'A', o devuelve '' si no hay grupo."""
    if not group or not group.startswith("GROUP_"):
        return ""
    return group.replace("GROUP_", "")


# ── Squad / player sync ───────────────────────────────────────────────────────

# Mapeo de posición de la API al choice de Player.Position.
POSITION_MAP = {
    "Goalkeeper": "GK",
    "Defender":   "DEF",
    "Midfielder": "MID",
    "Offence":    "FWD",
    "Forward":    "FWD",
}


def get_competition_teams():
    """
    Devuelve la lista de selecciones del Mundial junto con sus planteles.

    REQUIERE plan de pago en Football-Data.org (mínimo €29/mes).
    Con el tier gratuito la API devuelve 403.
    """
    url = f"{BASE_URL}/competitions/{COMPETITION_CODE}/teams"
    headers = {"X-Auth-Token": _get_api_key()}
    response = requests.get(url, headers=headers, timeout=15)

    if response.status_code == 403:
        raise FootballDataError(
            "Squad data requires a paid Football-Data.org tier. "
            "The current API key does not have access to /competitions/WC/teams. "
            "See https://www.football-data.org/pricing — upgrade to 'Free + Deep Data' (€29/mo) or higher."
        )
    if response.status_code == 429:
        raise FootballDataError("Rate limit alcanzado. Esperá unos minutos.")
    if response.status_code != 200:
        raise FootballDataError(f"API devolvió status {response.status_code}: {response.text}")

    return response.json().get("teams", [])


def sync_players():
    """
    Sincroniza los planteles del Mundial desde Football-Data.org al modelo Player.

    - Hace upsert por external_id.
    - Marca is_active=False en jugadores que ya no aparecen en la respuesta.
    - Retorna un dict {created, updated, deactivated}.

    Eleva FootballDataError si el API key no tiene acceso (ver get_competition_teams).
    """
    from predictions.models import Player, Team  # import local para evitar circular

    teams_data = get_competition_teams()

    created = updated = 0
    external_ids_seen: set[int] = set()

    for team_data in teams_data:
        tla = api_tla_to_team_code(team_data.get("tla"))
        try:
            team = Team.objects.get(code=tla)
        except Team.DoesNotExist:
            continue

        for member in team_data.get("squad", []):
            ext_id = member.get("id")
            if not ext_id:
                continue
            external_ids_seen.add(ext_id)

            dob_str = member.get("dateOfBirth")
            dob = date.fromisoformat(dob_str) if dob_str else None

            _, was_created = Player.objects.update_or_create(
                external_id=ext_id,
                defaults={
                    "name":          member.get("name", ""),
                    "team":          team,
                    "position":      POSITION_MAP.get(member.get("position", ""), ""),
                    "shirt_number":  member.get("shirtNumber"),
                    "date_of_birth": dob,
                    "is_active":     True,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

    # Jugadores que estaban en DB pero no aparecieron → ya no están en el plantel
    deactivated = (
        Player.objects
        .filter(external_id__isnull=False, is_active=True)
        .exclude(external_id__in=external_ids_seen)
        .update(is_active=False)
    )

    return {"created": created, "updated": updated, "deactivated": deactivated}