"""
Internal API views — not part of the user-facing UI.

Currently exposes a single endpoint used by the automated cron sync:
  POST /api/sync/world-cup/   (protected by X-Sync-Token header)
"""
import logging
import time

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from predictions.services.football_data import FootballDataError, sync_world_cup_matches

logger = logging.getLogger(__name__)

# Minimum seconds between consecutive sync calls (anti-spam / misconfigured cron guard).
_COOLDOWN_SECONDS = 300  # 5 minutes

# Module-level timestamp of last successful sync request (epoch float).
# Works correctly on Render's single-process free tier; resets on each deploy, which is fine.
_last_sync_time: float = 0.0


@csrf_exempt
@require_POST
def sync_world_cup_view(request):
    """
    Trigger a Football-Data.org sync.

    Authentication: X-Sync-Token header must match the SYNC_TOKEN env var.
    Cooldown: returns 429 if called within 5 minutes of the last successful run.
    """
    global _last_sync_time

    # ── Token auth ────────────────────────────────────────────────────────────
    expected = getattr(settings, "SYNC_TOKEN", "")
    provided = request.META.get("HTTP_X_SYNC_TOKEN", "")

    if not expected or provided != expected:
        logger.warning("sync_world_cup_view: unauthorized request")
        return JsonResponse({"ok": False, "error": "Unauthorized"}, status=401)

    # ── Cooldown ──────────────────────────────────────────────────────────────
    now = time.time()
    elapsed = now - _last_sync_time
    if elapsed < _COOLDOWN_SECONDS:
        remaining = int(_COOLDOWN_SECONDS - elapsed)
        logger.info("sync_world_cup_view: cooldown active, %ds remaining", remaining)
        return JsonResponse(
            {"ok": False, "error": f"Too soon. Wait {remaining}s before next sync."},
            status=429,
        )

    # ── Execute sync ──────────────────────────────────────────────────────────
    try:
        result = sync_world_cup_matches()
        _last_sync_time = now
        logger.info(
            "sync_world_cup_view: OK — created=%d updated=%d score_updated=%d",
            result["created"], result["updated"], result["score_updated"],
        )
        return JsonResponse({"ok": True, **result})
    except FootballDataError as exc:
        logger.error("sync_world_cup_view: FootballDataError — %s", exc)
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)
    except Exception:
        logger.exception("sync_world_cup_view: unexpected error")
        return JsonResponse({"ok": False, "error": "Internal server error"}, status=500)
