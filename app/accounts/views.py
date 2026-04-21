from django.shortcuts import render, redirect
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from .models import UserSettings


def registro(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('home')
    else:
        form = UserCreationForm()
    return render(request, 'accounts/registro.html', {'form': form})


@login_required
def reglamento(request):
    return render(request, 'accounts/reglamento.html')


@login_required
@require_POST
def marcar_reglas_vistas(request):
    settings, _ = UserSettings.objects.get_or_create(user=request.user)
    settings.rules_seen = True
    settings.save()
    return JsonResponse({'ok': True})