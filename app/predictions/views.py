import json

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (
    Match, SpecialPrediction, GroupPrediction,
    ThirdPlaceRanking, ThirdPlaceRankingEntry, BracketPrediction,
)
from tournaments.models import Tournament, TournamentMember
from .services.bracket_resolver import resolve_user_bracket

_GROUPS = list("ABCDEFGHIJKL")


def _member_or_403(request, tournament):
    return TournamentMember.objects.filter(
        tournament=tournament, user=request.user
    ).exists()


def _teams_by_group():
    """Returns {group_letter: {pk: Team}} from GROUP stage matches."""
    result = {}
    for match in (
        Match.objects.filter(stage=Match.Stage.GROUP)
        .select_related("home_team", "away_team")
    ):
        g = match.group
        if not g:
            continue
        result.setdefault(g, {})
        if match.home_team:
            result[g][match.home_team.pk] = match.home_team
        if match.away_team:
            result[g][match.away_team.pk] = match.away_team
    return result


@login_required
def bracket(request, tournament_id):
    tournament = get_object_or_404(Tournament, id=tournament_id)

    if not _member_or_403(request, tournament):
        messages.error(request, "No eres miembro de este torneo.")
        return redirect("mis_torneos")

    # Prerequisites
    existing_preds = GroupPrediction.objects.filter(user=request.user, tournament=tournament)
    completed_groups = sum(
        1 for gp in existing_preds
        if gp.first_team_id and gp.second_team_id and gp.third_team_id
    )
    grupos_guardados = completed_groups == 12
    terceros_guardados = ThirdPlaceRanking.objects.filter(
        user=request.user, tournament=tournament
    ).exists()
    bracket_listo = grupos_guardados and terceros_guardados

    rondas = None
    final_match = None

    if bracket_listo:
        knockout_stages = [
            Match.Stage.ROUND_OF_32,
            Match.Stage.ROUND_OF_16,
            Match.Stage.QUARTER_FINAL,
            Match.Stage.SEMI_FINAL,
            Match.Stage.FINAL,
        ]
        knockout_matches = list(
            Match.objects.filter(stage__in=knockout_stages)
            .select_related("home_team", "away_team")
            .order_by("match_datetime")
        )
        resolved = resolve_user_bracket(request.user, tournament, knockout_matches)

        matches_by_stage = {stage: [] for stage in knockout_stages}
        for match in knockout_matches:
            home, away = resolved.get(match.id, (None, None))
            matches_by_stage[match.stage].append({
                "match": match,
                "home":  home,
                "away":  away,
            })

        rondas_list = [
            {"label": "16avos",  "matches": matches_by_stage[Match.Stage.ROUND_OF_32]},
            {"label": "Octavos", "matches": matches_by_stage[Match.Stage.ROUND_OF_16]},
            {"label": "Cuartos", "matches": matches_by_stage[Match.Stage.QUARTER_FINAL]},
            {"label": "Semis",   "matches": matches_by_stage[Match.Stage.SEMI_FINAL]},
            {"label": "Final",   "matches": matches_by_stage[Match.Stage.FINAL]},
        ]
        final_matches = matches_by_stage[Match.Stage.FINAL]
        final_match = final_matches[0] if final_matches else None

        champion = None
        if final_match:
            bp = BracketPrediction.objects.filter(
                user=request.user, tournament=tournament, match=final_match["match"]
            ).select_related("predicted_winner").first()
            champion = bp.predicted_winner if bp else None

    return render(request, "predictions/bracket.html", {
        "tournament":         tournament,
        "grupos_guardados":   grupos_guardados,
        "terceros_guardados": terceros_guardados,
        "bracket_listo":      bracket_listo,
        "rondas_list":        rondas_list if bracket_listo else None,
        "final_match":        final_match if bracket_listo else None,
        "champion":           champion if bracket_listo else None,
    })


@login_required
def mis_predicciones(request, tournament_id):
    tournament = get_object_or_404(Tournament, id=tournament_id)

    if not _member_or_403(request, tournament):
        messages.error(request, "No eres miembro de este torneo.")
        return redirect("mis_torneos")

    tbg = _teams_by_group()

    existing_preds = {
        gp.group: gp
        for gp in GroupPrediction.objects.filter(
            user=request.user, tournament=tournament
        ).select_related("first_team", "second_team", "third_team")
    }

    # Build group display data: each group gets 4 teams in order
    # (saved 1st/2nd/3rd first, remaining team last, alphabetically)
    groups_data = []
    for g in _GROUPS:
        if g not in tbg:
            continue
        pred = existing_preds.get(g)
        pool = dict(tbg[g])

        slots = [None, None, None, None]
        if pred:
            for i, team in enumerate([pred.first_team, pred.second_team, pred.third_team]):
                if team and team.pk in pool:
                    slots[i] = team
                    del pool[team.pk]

        remaining = sorted(pool.values(), key=lambda t: t.name)
        for i in range(4):
            if slots[i] is None and remaining:
                slots[i] = remaining.pop(0)

        groups_data.append({"group": g, "teams": slots})

    completed_groups = sum(
        1 for gp in existing_preds.values()
        if gp.first_team_id and gp.second_team_id and gp.third_team_id
    )

    # Third-place ranking data
    third_team_group = {
        gp.third_team_id: gp.group
        for gp in existing_preds.values()
        if gp.third_team_id
    }

    third_teams = [
        {"group": gp.group, "team": gp.third_team}
        for g in _GROUPS
        if (gp := existing_preds.get(g)) and gp.third_team
    ]

    try:
        ranking_obj = ThirdPlaceRanking.objects.prefetch_related(
            "entries__team"
        ).get(user=request.user, tournament=tournament)
        saved_entries = [
            {
                "team":     e.team,
                "position": e.position,
                "group":    third_team_group.get(e.team.pk, "?"),
            }
            for e in sorted(ranking_obj.entries.all(), key=lambda e: e.position)
        ]
    except ThirdPlaceRanking.DoesNotExist:
        saved_entries = []

    ranked_pks = {e["team"].pk for e in saved_entries}
    unranked_terceros = [
        item for item in third_teams if item["team"].pk not in ranked_pks
    ]

    return render(request, "predictions/mis_predicciones.html", {
        "tournament":        tournament,
        "groups_data":       groups_data,
        "completed_groups":  completed_groups,
        "grupos_guardados":  completed_groups == 12,
        "third_teams":       third_teams,
        "saved_entries":     saved_entries,
        "unranked_terceros": unranked_terceros,
        "terceros_complete": len(third_teams) == 12,
    })


@login_required
@require_POST
def save_group_prediction(request, tournament_id, group_letter):
    tournament = get_object_or_404(Tournament, id=tournament_id)

    if not _member_or_403(request, tournament):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

    group_letter = group_letter.upper()
    if group_letter not in _GROUPS:
        return JsonResponse({"ok": False, "error": "invalid group"}, status=400)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "invalid json"}, status=400)

    # Valid team IDs for this group
    valid_ids = set()
    for match in Match.objects.filter(
        stage=Match.Stage.GROUP, group=group_letter
    ).select_related("home_team", "away_team"):
        if match.home_team:
            valid_ids.add(match.home_team.pk)
        if match.away_team:
            valid_ids.add(match.away_team.pk)

    def parse_id(val):
        try:
            tid = int(val)
            return tid if tid in valid_ids else None
        except (TypeError, ValueError):
            return None

    first_id  = parse_id(data.get("first"))
    second_id = parse_id(data.get("second"))
    third_id  = parse_id(data.get("third"))

    chosen = [t for t in [first_id, second_id, third_id] if t is not None]
    if len(chosen) != len(set(chosen)):
        return JsonResponse({"ok": False, "error": "duplicate teams"}, status=400)

    old_pred = GroupPrediction.objects.filter(
        user=request.user, tournament=tournament, group=group_letter
    ).first()
    old_third_id = old_pred.third_team_id if old_pred else None

    GroupPrediction.objects.update_or_create(
        user=request.user, tournament=tournament, group=group_letter,
        defaults={
            "first_team_id":  first_id,
            "second_team_id": second_id,
            "third_team_id":  third_id,
        },
    )

    # Silent replacement in ThirdPlaceRanking if third_team changed
    ranking_updated = False
    if third_id != old_third_id:
        try:
            ranking = ThirdPlaceRanking.objects.get(
                user=request.user, tournament=tournament
            )
            if old_third_id:
                updated = ranking.entries.filter(team_id=old_third_id).update(
                    team_id=third_id
                )
                ranking_updated = bool(updated) and third_id is not None
        except ThirdPlaceRanking.DoesNotExist:
            pass

    return JsonResponse({"ok": True, "ranking_updated": ranking_updated})


@login_required
@require_POST
def save_terceros(request, tournament_id):
    tournament = get_object_or_404(Tournament, id=tournament_id)

    if not _member_or_403(request, tournament):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "invalid json"}, status=400)

    order_str = data.get("order", "")
    try:
        ordered_ids = [int(x) for x in str(order_str).split(",") if x.strip()]
    except ValueError:
        return JsonResponse({"ok": False, "error": "invalid order"}, status=400)

    valid_third_ids = set(
        GroupPrediction.objects.filter(
            user=request.user, tournament=tournament
        ).exclude(third_team=None).values_list("third_team_id", flat=True)
    )
    ordered_ids = [tid for tid in ordered_ids if tid in valid_third_ids]

    if len(ordered_ids) < 8:
        return JsonResponse({"ok": False, "error": "need 8 teams"}, status=400)

    ranking_obj, _ = ThirdPlaceRanking.objects.get_or_create(
        user=request.user, tournament=tournament
    )
    ranking_obj.entries.all().delete()
    ThirdPlaceRankingEntry.objects.bulk_create([
        ThirdPlaceRankingEntry(ranking=ranking_obj, team_id=tid, position=pos)
        for pos, tid in enumerate(ordered_ids[:8], start=1)
    ])

    return JsonResponse({"ok": True})


@login_required
def ranking(request, tournament_id):
    tournament = get_object_or_404(Tournament, id=tournament_id)

    if not _member_or_403(request, tournament):
        messages.error(request, "No eres miembro de este torneo.")
        return redirect("mis_torneos")

    members = TournamentMember.objects.filter(tournament=tournament).select_related("user")

    ranking_list = []
    for i, member in enumerate(members, start=1):
        ranking_list.append({
            "user":     member.user,
            "points":   0,
            "position": i,
            "medal":    "",
            "initials": member.user.username[:2].upper(),
        })

    special_predictions = SpecialPrediction.objects.filter(
        tournament=tournament, user__in=[m.user for m in members]
    ).select_related("user")

    return render(request, "predictions/ranking.html", {
        "tournament":        tournament,
        "ranking_list":      ranking_list,
        "most_exact_users":  [],
        "special_predictions": special_predictions,
    })


@login_required
def predicciones_especiales(request, tournament_id):
    tournament = get_object_or_404(Tournament, id=tournament_id)

    if not _member_or_403(request, tournament):
        messages.error(request, "No eres miembro de este torneo.")
        return redirect("mis_torneos")

    deadline = settings.SPECIAL_PREDICTIONS_DEADLINE
    is_open = timezone.now() < deadline

    special = SpecialPrediction.objects.filter(
        user=request.user, tournament=tournament,
    ).first()

    if request.method == "POST" and is_open:
        golden_ball = request.POST.get("golden_ball", "").strip()
        golden_boot = request.POST.get("golden_boot", "").strip()
        SpecialPrediction.objects.update_or_create(
            user=request.user,
            tournament=tournament,
            defaults={"golden_ball": golden_ball, "golden_boot": golden_boot},
        )
        messages.success(request, "¡Predicciones especiales guardadas!")
        return redirect("predicciones_especiales", tournament_id=tournament_id)

    return render(request, "predictions/predicciones_especiales.html", {
        "tournament": tournament,
        "special":    special,
        "is_open":    is_open,
        "deadline":   deadline,
    })


def home(request):
    if request.user.is_authenticated:
        return redirect("mis_torneos")
    return redirect("login")
