from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.contrib.auth.models import User
from itertools import groupby
from .models import Match, Prediction
from tournaments.models import Tournament, TournamentMember


@login_required
def fixture(request, tournament_id):
    tournament = get_object_or_404(Tournament, id=tournament_id)

    # Verificar que el usuario es miembro del torneo
    if not TournamentMember.objects.filter(tournament=tournament, user=request.user).exists():
        messages.error(request, 'No eres miembro de este torneo.')
        return redirect('mis_torneos')

    matches = Match.objects.select_related('home_team', 'away_team').order_by('match_datetime')

    if request.method == 'POST':
        for match in matches:
            if match.match_datetime > timezone.now():
                home_score = request.POST.get(f'home_{match.id}')
                away_score = request.POST.get(f'away_{match.id}')
                if home_score is not None and away_score is not None:
                    Prediction.objects.update_or_create(
                        user=request.user,
                        match=match,
                        tournament=tournament,
                        defaults={
                            'home_score': home_score,
                            'away_score': away_score,
                        }
                    )
        return redirect('fixture', tournament_id=tournament_id)

    predictions = Prediction.objects.filter(user=request.user, tournament=tournament)
    predictions_map = {p.match_id: p for p in predictions}

    match_list = []
    for match in matches:
        prediction = predictions_map.get(match.id)
        match_list.append({
            'match': match,
            'home_score': prediction.home_score if prediction else '',
            'away_score': prediction.away_score if prediction else '',
            'editable': match.match_datetime > timezone.now(),
        })

    match_list_grouped = []
    for fecha, grupo in groupby(match_list, key=lambda x: x['match'].match_datetime.date()):
        match_list_grouped.append({
            'fecha': fecha,
            'partidos': list(grupo),
        })

    return render(request, 'predictions/fixture.html', {
        'tournament': tournament,
        'match_list_grouped': match_list_grouped,
        'now': timezone.now(),
    })


@login_required
def mis_predicciones(request, tournament_id):
    tournament = get_object_or_404(Tournament, id=tournament_id)

    if not TournamentMember.objects.filter(tournament=tournament, user=request.user).exists():
        messages.error(request, 'No eres miembro de este torneo.')
        return redirect('mis_torneos')

    predictions = Prediction.objects.filter(
        user=request.user,
        tournament=tournament,
    ).select_related('match', 'match__home_team', 'match__away_team').order_by('match__match_datetime')

    def get_state(prediction):
        if prediction.points is None:
            return 'pending'
        elif prediction.points >= 1:
            return 'correct'
        else:
            return 'wrong'

    predictions_grouped = []
    for fecha, grupo in groupby(predictions, key=lambda p: p.match.match_datetime.date()):
        predicciones = [
            {
                'prediction': p,
                'state': get_state(p),
            }
            for p in grupo
        ]
        predictions_grouped.append({
            'fecha': fecha,
            'predicciones': predicciones,
        })

    return render(request, 'predictions/mis_predicciones.html', {
        'tournament': tournament,
        'predictions_grouped': predictions_grouped,
    })


@login_required
def ranking(request, tournament_id):
    tournament = get_object_or_404(Tournament, id=tournament_id)

    if not TournamentMember.objects.filter(tournament=tournament, user=request.user).exists():
        messages.error(request, 'No eres miembro de este torneo.')
        return redirect('mis_torneos')

    members = TournamentMember.objects.filter(
        tournament=tournament
    ).select_related('user')

    def get_medal(position):
        if position == 1:
            return 'gold'
        elif position == 2:
            return 'silver'
        elif position == 3:
            return 'bronze'
        return ''

    ranking_list = []
    for member in members:
        predictions = Prediction.objects.filter(user=member.user, tournament=tournament)
        total_points = sum(p.points for p in predictions if p.points is not None)
        ranking_list.append({
            'user': member.user,
            'points': total_points,
            'initials': member.user.username[:2].upper(),
        })

    ranking_list.sort(key=lambda x: x['points'], reverse=True)

    for i, item in enumerate(ranking_list, start=1):
        item['position'] = i
        item['medal'] = get_medal(i)

    return render(request, 'predictions/ranking.html', {
        'tournament': tournament,
        'ranking_list': ranking_list,
    })


def home(request):
    if request.user.is_authenticated:
        return redirect('mis_torneos')
    return redirect('login')