"""
Shared utilities for the predictions app.
"""
from functools import lru_cache, wraps

from django.http import JsonResponse
from django.utils.timezone import now as _now


@lru_cache(maxsize=1)
def get_tournament_deadline():
    """
    Return the datetime of the earliest Match in the DB — i.e. the World Cup kickoff.

    This is the single shared deadline for ALL prediction categories
    (groups, thirds, bracket, trophies).

    Result is cached for the lifetime of the process. A redeploy resets it, which is
    intentional: the first-match datetime never changes in production.
    Returns None if no matches are loaded (edge case; should not happen in prod).
    """
    from predictions.models import Match
    return (
        Match.objects
        .order_by("match_datetime")
        .values_list("match_datetime", flat=True)
        .first()
    )


def require_before_deadline(view_func):
    """
    Decorator for JSON write endpoints.
    Returns HTTP 403 {"ok": false, "error": "..."} if the deadline has passed.
    Apply after @login_required and @require_POST.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        deadline = get_tournament_deadline()
        if deadline is not None and _now() >= deadline:
            return JsonResponse(
                {"ok": False, "error": "Las predicciones cerraron al iniciar el Mundial."},
                status=403,
            )
        return view_func(request, *args, **kwargs)
    return wrapper
