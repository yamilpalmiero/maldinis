"""Cliente para Football-Data.org API v4."""
import os
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