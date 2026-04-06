from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from predictions.models import SpecialPrediction
from .models import Tournament, TournamentMember


@login_required
def mis_torneos(request):
    memberships = list(TournamentMember.objects.filter(
        user=request.user
    ).select_related('tournament'))

    tournament_ids = [m.tournament.id for m in memberships]

    special_predictions = SpecialPrediction.objects.filter(
        user=request.user,
        tournament_id__in=tournament_ids
    )
    special_map = {sp.tournament_id: sp for sp in special_predictions}

    memberships_data = []
    for membership in memberships:
        sp = special_map.get(membership.tournament.id)
        memberships_data.append({
            'membership': membership,
            'special': sp,
        })

    return render(request, 'tournaments/mis_torneos.html', {
        'memberships_data': memberships_data,
    })


@login_required
def crear_torneo(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'El nombre del torneo no puede estar vacío.')
            return redirect('crear_torneo')

        # Verificar nombre duplicado para este usuario
        if Tournament.objects.filter(created_by=request.user, name__iexact=name).exists():
            messages.error(request, f'Ya tenés un torneo llamado "{name}".')
            return redirect('crear_torneo')

        tournament = Tournament.objects.create(
            name=name,
            created_by=request.user,
        )
        TournamentMember.objects.create(
            tournament=tournament,
            user=request.user,
            role=TournamentMember.Role.ADMIN,
        )
        messages.success(request, f'Torneo "{tournament.name}" creado. Código de invitación: {tournament.invite_code}')
        return redirect('mis_torneos')

    return render(request, 'tournaments/crear_torneo.html')


@login_required
def unirse_torneo(request):
    if request.method == 'POST':
        code = request.POST.get('invite_code', '').strip().upper()
        tournament = Tournament.objects.filter(invite_code=code).first()

        if not tournament:
            messages.error(request, 'Código de invitación inválido.')
            return redirect('unirse_torneo')

        if TournamentMember.objects.filter(tournament=tournament, user=request.user).exists():
            messages.error(request, 'Ya eres miembro de este torneo.')
            return redirect('mis_torneos')

        TournamentMember.objects.create(
            tournament=tournament,
            user=request.user,
            role=TournamentMember.Role.MEMBER,
        )
        messages.success(request, f'Te uniste al torneo "{tournament.name}".')
        return redirect('mis_torneos')

    return render(request, 'tournaments/unirse_torneo.html')

@login_required
def eliminar_torneo(request, tournament_id):
    tournament = get_object_or_404(Tournament, id=tournament_id)
    membership = get_object_or_404(TournamentMember, tournament=tournament, user=request.user)

    if membership.role != TournamentMember.Role.ADMIN:
        messages.error(request, 'Solo el administrador puede eliminar el torneo.')
        return redirect('mis_torneos')

    if request.method == 'POST':
        name = tournament.name
        tournament.delete()
        messages.success(request, f'Torneo "{name}" eliminado.')
        return redirect('mis_torneos')

    return redirect('mis_torneos')