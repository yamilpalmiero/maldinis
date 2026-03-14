from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Tournament, TournamentMember


@login_required
def mis_torneos(request):
    memberships = TournamentMember.objects.filter(
        user=request.user
    ).select_related('tournament')

    return render(request, 'tournaments/mis_torneos.html', {
        'memberships': memberships,
    })


@login_required
def crear_torneo(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'El nombre del torneo no puede estar vacío.')
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