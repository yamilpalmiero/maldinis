# 1. Librería estándar de Python
from itertools import groupby

# 2. Librerías de terceros
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.conf import settings

# 3. Imports propios del proyecto
from .models import Match, SpecialPrediction
from tournaments.models import Tournament, TournamentMember


@login_required
def fixture(request, tournament_id):
    tournament = get_object_or_404(Tournament, id=tournament_id)

    if not TournamentMember.objects.filter(
        tournament=tournament, user=request.user
    ).exists():
        messages.error(request, "No eres miembro de este torneo.")
        return redirect("mis_torneos")

    matches = (
        Match.objects.filter(stage=Match.Stage.GROUP)
        .select_related("home_team", "away_team")
        .order_by("match_datetime")
    )

    match_list = [{"match": m} for m in matches]

    match_list_grouped = []
    for fecha, grupo in groupby(
        match_list, key=lambda x: x["match"].match_datetime.date()
    ):
        match_list_grouped.append({"fecha": fecha, "partidos": list(grupo)})

    groups_order = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"]
    by_group = {}
    for item in match_list:
        g = item["match"].group
        if g:
            by_group.setdefault(g, []).append(item)

    match_list_by_group = [
        {"grupo": g, "partidos": by_group[g]} for g in groups_order if g in by_group
    ]

    return render(
        request,
        "predictions/fixture.html",
        {
            "tournament": tournament,
            "match_list_grouped": match_list_grouped,
            "match_list_by_group": match_list_by_group,
        },
    )


@login_required
def bracket(request, tournament_id):
    tournament = get_object_or_404(Tournament, id=tournament_id)

    if not TournamentMember.objects.filter(
        tournament=tournament, user=request.user
    ).exists():
        messages.error(request, "No eres miembro de este torneo.")
        return redirect("mis_torneos")

    knockout_stages = [
        Match.Stage.ROUND_OF_32,
        Match.Stage.ROUND_OF_16,
        Match.Stage.QUARTER_FINAL,
        Match.Stage.SEMI_FINAL,
        Match.Stage.THIRD_PLACE,
        Match.Stage.FINAL,
    ]

    matches = (
        Match.objects.filter(stage__in=knockout_stages)
        .select_related("home_team", "away_team")
        .order_by("match_datetime")
    )

    stage_labels = {
        Match.Stage.ROUND_OF_32: "Dieciseisavos",
        Match.Stage.ROUND_OF_16: "Octavos",
        Match.Stage.QUARTER_FINAL: "Cuartos",
        Match.Stage.SEMI_FINAL: "Semis",
        Match.Stage.THIRD_PLACE: "3er puesto",
        Match.Stage.FINAL: "Final",
    }

    matches_by_stage = {stage: [] for stage in knockout_stages}
    for match in matches:
        matches_by_stage[match.stage].append({"match": match})

    bracket_columns = [
        {"label": stage_labels[Match.Stage.ROUND_OF_32],   "partidos": matches_by_stage[Match.Stage.ROUND_OF_32]},
        {"label": stage_labels[Match.Stage.ROUND_OF_16],   "partidos": matches_by_stage[Match.Stage.ROUND_OF_16]},
        {"label": stage_labels[Match.Stage.QUARTER_FINAL], "partidos": matches_by_stage[Match.Stage.QUARTER_FINAL]},
        {"label": stage_labels[Match.Stage.SEMI_FINAL],    "partidos": matches_by_stage[Match.Stage.SEMI_FINAL]},
        {
            "label": "Final / 3er puesto",
            "partidos": (
                matches_by_stage[Match.Stage.FINAL]
                + matches_by_stage[Match.Stage.THIRD_PLACE]
            ),
        },
    ]

    return render(
        request,
        "predictions/bracket.html",
        {
            "tournament": tournament,
            "bracket_columns": bracket_columns,
        },
    )


@login_required
def mis_predicciones(request, tournament_id):
    tournament = get_object_or_404(Tournament, id=tournament_id)

    if not TournamentMember.objects.filter(
        tournament=tournament, user=request.user
    ).exists():
        messages.error(request, "No eres miembro de este torneo.")
        return redirect("mis_torneos")

    return render(
        request,
        "predictions/mis_predicciones.html",
        {"tournament": tournament},
    )


@login_required
def ranking(request, tournament_id):
    tournament = get_object_or_404(Tournament, id=tournament_id)

    if not TournamentMember.objects.filter(
        tournament=tournament, user=request.user
    ).exists():
        messages.error(request, "No eres miembro de este torneo.")
        return redirect("mis_torneos")

    members = TournamentMember.objects.filter(tournament=tournament).select_related("user")

    ranking_list = []
    for i, member in enumerate(members, start=1):
        ranking_list.append({
            "user": member.user,
            "points": 0,
            "position": i,
            "medal": "",
            "initials": member.user.username[:2].upper(),
        })

    special_predictions = SpecialPrediction.objects.filter(
        tournament=tournament, user__in=[m.user for m in members]
    ).select_related("user")

    return render(
        request,
        "predictions/ranking.html",
        {
            "tournament": tournament,
            "ranking_list": ranking_list,
            "most_exact_users": [],
            "special_predictions": special_predictions,
        },
    )


@login_required
def predicciones_especiales(request, tournament_id):
    tournament = get_object_or_404(Tournament, id=tournament_id)

    if not TournamentMember.objects.filter(
        tournament=tournament, user=request.user
    ).exists():
        messages.error(request, "No eres miembro de este torneo.")
        return redirect("mis_torneos")

    deadline = settings.SPECIAL_PREDICTIONS_DEADLINE
    is_open = timezone.now() < deadline

    special = SpecialPrediction.objects.filter(
        user=request.user,
        tournament=tournament,
    ).first()

    if request.method == "POST" and is_open:
        golden_ball = request.POST.get("golden_ball", "").strip()
        golden_boot = request.POST.get("golden_boot", "").strip()

        SpecialPrediction.objects.update_or_create(
            user=request.user,
            tournament=tournament,
            defaults={
                "golden_ball": golden_ball,
                "golden_boot": golden_boot,
            },
        )
        messages.success(request, "¡Predicciones especiales guardadas!")
        return redirect("predicciones_especiales", tournament_id=tournament_id)

    return render(
        request,
        "predictions/predicciones_especiales.html",
        {
            "tournament": tournament,
            "special": special,
            "is_open": is_open,
            "deadline": deadline,
        },
    )


def home(request):
    if request.user.is_authenticated:
        return redirect("mis_torneos")
    return redirect("login")
