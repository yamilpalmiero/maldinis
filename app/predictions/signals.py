# 1. Librerías de terceros
from django.db.models.signals import post_save
from django.dispatch import receiver

# 2. Imports propios del proyecto
from .models import Match, Prediction


def calculate_points(match_home, match_away, pred_home, pred_away):
    """Devuelve los puntos correspondientes a una predicción dado el resultado real."""
    # Resultado exacto
    if pred_home == match_home and pred_away == match_away:
        return 3

    # Ganó local en ambos
    if match_home > match_away and pred_home > pred_away:
        return 1

    # Ganó visitante en ambos
    if match_home < match_away and pred_home < pred_away:
        return 1

    # Empate en ambos
    if match_home == match_away and pred_home == pred_away:
        return 1

    return 0


@receiver(post_save, sender=Match)
def score_predictions_on_result(sender, instance, **kwargs):
    """
    Se ejecuta automáticamente cada vez que se guarda un Match en el Admin.
    Si el partido tiene resultado completo, recalcula los puntos de todas
    las predicciones asociadas.
    """
    if instance.home_score is None or instance.away_score is None:
        return

    predictions = Prediction.objects.filter(match=instance)

    for prediction in predictions:
        prediction.points = calculate_points(
            instance.home_score,
            instance.away_score,
            prediction.home_score,
            prediction.away_score,
        )
        prediction.save()