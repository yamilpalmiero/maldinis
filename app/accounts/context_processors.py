from .models import UserSettings


def rules_modal(request):
    if not request.user.is_authenticated:
        return {'show_rules_modal': False}

    settings, _ = UserSettings.objects.get_or_create(user=request.user)
    if settings.rules_seen:
        return {'show_rules_modal': False}

    # Ya se mostró en esta sesión, no volver a mostrarlo hasta el próximo login
    if request.session.get('rules_shown'):
        return {'show_rules_modal': False}

    request.session['rules_shown'] = True
    return {'show_rules_modal': True}