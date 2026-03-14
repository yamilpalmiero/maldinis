from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from .models import Match, Prediction
from django.contrib.auth.models import User
from itertools import groupby
from datetime import date


@login_required
def fixture(request):
    matches = Match.objects.select_related('home_team', 'away_team').order_by('match_datetime')

    if request.method == 'POST':
        for match in matches:
            if match.date > timezone.now():
                goals_home = request.POST.get(f'home_{match.id}')
                goals_away = request.POST.get(f'away_{match.id}')
                if goals_home is not None and goals_away is not None:
                    Prediction.objects.update_or_create(
                        user=request.user,
                        match=match,
                        defaults={
                            'goals_home': goals_home,
                            'goals_away': goals_away,
                        }
                    )
        return redirect('fixture')

    predictions = Prediction.objects.filter(user=request.user)
    predictions_map = {p.match_id: p for p in predictions}

    match_list = []
    for match in matches:
        prediction = predictions_map.get(match.id)
        match_list.append({
            'match': match,
            'goals_home': prediction.goals_home if prediction else '',
            'goals_away': prediction.goals_away if prediction else '',
            'editable': match.match_datetime > timezone.now(),
        })

    # Agrupar partidos por fecha
    match_list_grouped = []
    for fecha, grupo in groupby(match_list, key=lambda x: x['match'].match_datetime.date()):
        match_list_grouped.append({
            'fecha': fecha,
            'partidos': list(grupo),
        })

    return render(request, 'predictions/fixture.html', {
        'match_list_grouped': match_list_grouped,
        'now': timezone.now(),
    })



@login_required
def mis_predicciones(request):
    predictions = Prediction.objects.filter(
        user=request.user
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
        'predictions_grouped': predictions_grouped,
    })



@login_required
def ranking(request):
    users = User.objects.all()

    def get_medal(position):
        if position == 1:
            return 'gold'
        elif position == 2:
            return 'silver'
        elif position == 3:
            return 'bronze'
        return ''

    ranking_list = []
    for i, user in enumerate(users, start=1):
        predictions = Prediction.objects.filter(user=user)
        total_points = sum(p.points for p in predictions if p.points is not None)
        ranking_list.append({
            'user': user,
            'points': total_points,
            'initials': user.username[:2].upper(),
        })

    ranking_list.sort(key=lambda x: x['points'], reverse=True)

    for i, item in enumerate(ranking_list, start=1):
        item['position'] = i
        item['medal'] = get_medal(i)

    return render(request, 'predictions/ranking.html', {
        'ranking_list': ranking_list,
    })


def home(request):
    if request.user.is_authenticated:
        return redirect('fixture')
    return redirect('login')