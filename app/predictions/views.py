import json
import logging

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (
    Match, GroupPrediction,
    ThirdPlaceRanking, ThirdPlaceRankingEntry, BracketPrediction,
)
from tournaments.models import Tournament, TournamentMember
from .services.bracket_resolver import resolve_user_bracket
from .services.scoring import compute_user_score
from .utils import get_tournament_deadline, require_before_deadline

logger = logging.getLogger(__name__)

_GROUPS = list("ABCDEFGHIJKL")

_BRACKET_STAGES = [
    Match.Stage.ROUND_OF_32,
    Match.Stage.ROUND_OF_16,
    Match.Stage.QUARTER_FINAL,
    Match.Stage.SEMI_FINAL,
    Match.Stage.FINAL,
]


def _compute_source_ids(knockout_matches):
    """
    Returns {match_id: (home_src_id, away_src_id)} derived from positional bracket structure.
    R32: (None, None). R16[i]: (r32[i*2].id, r32[i*2+1].id). Etc.
    """
    by_stage = {}
    for m in sorted(knockout_matches, key=lambda m: m.match_datetime):
        by_stage.setdefault(m.stage, []).append(m)

    r32 = by_stage.get(Match.Stage.ROUND_OF_32, [])
    r16 = by_stage.get(Match.Stage.ROUND_OF_16, [])
    qf  = by_stage.get(Match.Stage.QUARTER_FINAL, [])
    sf  = by_stage.get(Match.Stage.SEMI_FINAL, [])
    fin = by_stage.get(Match.Stage.FINAL, [])

    result = {}
    for m in r32:
        result[m.id] = (None, None)
    for stage_matches, prev in [(r16, r32), (qf, r16), (sf, qf)]:
        for i, m in enumerate(stage_matches):
            h = prev[i * 2].id if i * 2 < len(prev) else None
            a = prev[i * 2 + 1].id if i * 2 + 1 < len(prev) else None
            result[m.id] = (h, a)
    for m in fin:
        result[m.id] = (sf[0].id if sf else None, sf[1].id if len(sf) > 1 else None)
    return result


def _compute_cascade_deletions(user, tournament, changed_match_id, old_winner_team_id):
    """
    Returns match IDs whose BracketPrediction must be deleted because they depended
    on old_winner_team_id advancing from changed_match_id.

    Uses positional bracket structure — does not read home_source/away_source from DB.
    """
    if old_winner_team_id is None:
        return []

    knockout_matches = list(
        Match.objects.filter(stage__in=_BRACKET_STAGES)
        .only("id", "match_datetime", "stage")
        .order_by("match_datetime")
    )
    source_ids = _compute_source_ids(knockout_matches)

    dep_map: dict[int, list[int]] = {}
    for m_id, (h_src, a_src) in source_ids.items():
        for src in (h_src, a_src):
            if src is not None:
                dep_map.setdefault(src, []).append(m_id)

    user_preds: dict[int, int] = {
        bp.match_id: bp.predicted_winner_id
        for bp in BracketPrediction.objects.filter(user=user, tournament=tournament)
    }

    to_delete: list[int] = []

    def _cascade(match_id: int, team_id: int) -> None:
        for downstream_id in dep_map.get(match_id, []):
            if user_preds.get(downstream_id) == team_id:
                to_delete.append(downstream_id)
                _cascade(downstream_id, team_id)

    _cascade(changed_match_id, old_winner_team_id)
    return to_delete


def _build_bracket_halves(all_match_items, knockout_matches):
    """
    Split knockout match items into left/right halves positionally.
    Left: r32[0:8], r16[0:4], qf[0:2], sf[0:1].
    Right: r32[8:16], r16[4:8], qf[2:4], sf[1:2].
    Returns (left, right, final_item).
    """
    by_id = {item["match"].id: item for item in all_match_items}

    by_stage = {}
    for m in sorted(knockout_matches, key=lambda m: m.match_datetime):
        by_stage.setdefault(m.stage, []).append(m)

    r32 = by_stage.get(Match.Stage.ROUND_OF_32, [])
    r16 = by_stage.get(Match.Stage.ROUND_OF_16, [])
    qf  = by_stage.get(Match.Stage.QUARTER_FINAL, [])
    sf  = by_stage.get(Match.Stage.SEMI_FINAL, [])
    fin = by_stage.get(Match.Stage.FINAL, [])

    def items(ms):
        return [by_id[m.id] for m in ms if m.id in by_id]

    final_item = items(fin)[0] if fin and fin[0].id in by_id else None

    left = {
        "r32": items(r32[:8]),
        "r16": items(r16[:4]),
        "qf":  items(qf[:2]),
        "sf":  items(sf[:1]),
    }
    right = {
        "r32": items(r32[8:]),
        "r16": items(r16[4:]),
        "qf":  items(qf[2:]),
        "sf":  items(sf[1:]),
    }
    return left, right, final_item


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

    bracket_left = bracket_right = final_match = champion = None
    bracket_error = False

    if bracket_listo:
        try:
            knockout_matches = list(
                Match.objects.filter(stage__in=_BRACKET_STAGES)
                .select_related("home_team", "away_team")
                .order_by("match_datetime")
            )
            resolved = resolve_user_bracket(request.user, tournament, knockout_matches)

            winner_map = {
                bp.match_id: bp.predicted_winner_id
                for bp in BracketPrediction.objects.filter(
                    user=request.user, tournament=tournament,
                    match__stage__in=_BRACKET_STAGES,
                )
            }

            source_ids = _compute_source_ids(knockout_matches)
            all_items = []
            for match in knockout_matches:
                home, away = resolved.get(match.id, (None, None))
                h_src_id, a_src_id = source_ids.get(match.id, (None, None))
                all_items.append({
                    "match":                match,
                    "home":                 home,
                    "away":                 away,
                    "home_source_match_id": h_src_id,
                    "away_source_match_id": a_src_id,
                    "winner_id":            winner_map.get(match.id),
                })

            bracket_left, bracket_right, final_match = _build_bracket_halves(all_items, knockout_matches)

            if final_match and not bracket_error:
                bp = BracketPrediction.objects.filter(
                    user=request.user, tournament=tournament, match=final_match["match"]
                ).select_related("predicted_winner").first()
                champion = bp.predicted_winner if bp else None

        except Exception:
            logger.error(
                "bracket: unexpected error resolving bracket for user=%s tournament=%s",
                request.user.pk, tournament.pk, exc_info=True,
            )
            bracket_error = True

    deadline = get_tournament_deadline()
    is_open  = deadline is None or timezone.now() < deadline

    return render(request, "predictions/bracket.html", {
        "tournament":         tournament,
        "grupos_guardados":   grupos_guardados,
        "terceros_guardados": terceros_guardados,
        "bracket_listo":      bracket_listo,
        "bracket_error":      bracket_error,
        "bracket_left":       bracket_left,
        "bracket_right":      bracket_right,
        "final_match":        final_match,
        "champion":           champion,
        "is_open":            is_open,
        "deadline":           deadline,
    })


@login_required
@require_POST
@require_before_deadline
def bracket_predict(request, tournament_id):
    tournament = get_object_or_404(Tournament, id=tournament_id)

    if not _member_or_403(request, tournament):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "invalid json"}, status=400)

    try:
        match_id = int(data.get("match_id"))
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "invalid match_id"}, status=400)

    winner_team_id = data.get("winner_team_id")

    try:
        match = Match.objects.get(id=match_id, stage__in=_BRACKET_STAGES)
    except Match.DoesNotExist:
        return JsonResponse({"ok": False, "error": "invalid match"}, status=400)

    # Capture old winner before any modifications (needed for cascade)
    old_winner_id = BracketPrediction.objects.filter(
        user=request.user, tournament=tournament, match=match
    ).values_list("predicted_winner_id", flat=True).first()

    if winner_team_id is None:
        # Clear action
        with transaction.atomic():
            BracketPrediction.objects.filter(
                user=request.user, tournament=tournament, match=match
            ).delete()
            deleted_ids = _compute_cascade_deletions(
                request.user, tournament, match_id, old_winner_id
            )
            if deleted_ids:
                BracketPrediction.objects.filter(
                    user=request.user, tournament=tournament, match_id__in=deleted_ids
                ).delete()
        return JsonResponse({"ok": True, "saved": None, "deleted": deleted_ids})

    try:
        winner_team_id = int(winner_team_id)
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "invalid winner_team_id"}, status=400)

    # Same winner re-sent: acknowledge without touching DB
    if winner_team_id == old_winner_id:
        return JsonResponse({
            "ok": True,
            "saved": {"match_id": match_id, "winner_team_id": winner_team_id},
            "deleted": [],
        })

    # Validate winner is one of the two teams resolved for this match
    knockout_matches = list(
        Match.objects.filter(stage__in=_BRACKET_STAGES)
        .select_related("home_team", "away_team")
        .order_by("match_datetime")
    )
    resolved = resolve_user_bracket(request.user, tournament, knockout_matches)
    home_team, away_team = resolved.get(match.id, (None, None))

    valid_ids = {t.pk for t in [home_team, away_team] if t is not None}
    if not valid_ids:
        return JsonResponse({"ok": False, "error": "teams not resolved"}, status=400)
    if winner_team_id not in valid_ids:
        return JsonResponse({"ok": False, "error": "invalid team"}, status=400)

    with transaction.atomic():
        BracketPrediction.objects.update_or_create(
            user=request.user,
            tournament=tournament,
            match=match,
            defaults={"predicted_winner_id": winner_team_id},
        )
        deleted_ids = _compute_cascade_deletions(
            request.user, tournament, match_id, old_winner_id
        )
        if deleted_ids:
            BracketPrediction.objects.filter(
                user=request.user, tournament=tournament, match_id__in=deleted_ids
            ).delete()

    return JsonResponse({
        "ok": True,
        "saved": {"match_id": match_id, "winner_team_id": winner_team_id},
        "deleted": deleted_ids,
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

    deadline = get_tournament_deadline()
    is_open  = deadline is None or timezone.now() < deadline

    return render(request, "predictions/mis_predicciones.html", {
        "tournament":        tournament,
        "groups_data":       groups_data,
        "completed_groups":  completed_groups,
        "grupos_guardados":  completed_groups == 12,
        "third_teams":       third_teams,
        "saved_entries":     saved_entries,
        "unranked_terceros": unranked_terceros,
        "terceros_complete": len(third_teams) == 12,
        "is_open":           is_open,
        "deadline":          deadline,
    })


@login_required
@require_POST
@require_before_deadline
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
@require_before_deadline
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

    return JsonResponse({
        "ok": True,
        "bracket_url": reverse("bracket", args=[tournament_id]),
    })


@login_required
def ranking(request, tournament_id):
    tournament = get_object_or_404(Tournament, id=tournament_id)

    if not _member_or_403(request, tournament):
        messages.error(request, "No eres miembro de este torneo.")
        return redirect("mis_torneos")

    members = list(
        TournamentMember.objects.filter(tournament=tournament).select_related("user")
    )

    # Campeón y subcampeón: 1 sola query para todos los miembros
    final_match = (
        Match.objects.filter(stage=Match.Stage.FINAL)
        .only("id").first()
    )
    sf_matches = list(
        Match.objects.filter(stage=Match.Stage.SEMI_FINAL)
        .only("id", "match_datetime")
        .order_by("match_datetime")
    )

    pred_map: dict[tuple[int, int], object] = {}
    if final_match or sf_matches:
        match_ids = [m.id for m in sf_matches] + ([final_match.id] if final_match else [])
        for bp in BracketPrediction.objects.filter(
            tournament=tournament,
            user_id__in=[m.user_id for m in members],
            match_id__in=match_ids,
        ).select_related("predicted_winner"):
            pred_map[(bp.user_id, bp.match_id)] = bp.predicted_winner

    sf_ids = [m.id for m in sf_matches]

    def _final_picks(user_id):
        if not final_match:
            return None, None
        champion = pred_map.get((user_id, final_match.id))
        if champion is None:
            return None, None
        sf0 = pred_map.get((user_id, sf_ids[0])) if len(sf_ids) > 0 else None
        sf1 = pred_map.get((user_id, sf_ids[1])) if len(sf_ids) > 1 else None
        if sf0 and sf0.pk == champion.pk:
            runner_up = sf1
        elif sf1 and sf1.pk == champion.pk:
            runner_up = sf0
        else:
            runner_up = None
        return champion, runner_up

    entries = []
    for m in members:
        champion, runner_up = _final_picks(m.user_id)
        entries.append({
            "user":      m.user,
            "score":     compute_user_score(m.user, tournament),
            "initials":  m.user.username[:2].upper(),
            "champion":  champion,
            "runner_up": runner_up,
        })
    entries.sort(key=lambda x: x["score"]["total"], reverse=True)
    for i, item in enumerate(entries, start=1):
        item["position"] = i

    return render(request, "predictions/ranking.html", {
        "tournament":   tournament,
        "ranking_list": entries,
    })


def home(request):
    if request.user.is_authenticated:
        return redirect("mis_torneos")
    return redirect("login")
