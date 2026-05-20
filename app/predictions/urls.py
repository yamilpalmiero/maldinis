from django.urls import path
from . import views

urlpatterns = [
    path('torneo/<int:tournament_id>/bracket/', views.bracket, name='bracket'),
    path('torneo/<int:tournament_id>/bracket/predict/', views.bracket_predict, name='bracket_predict'),
    path('torneo/<int:tournament_id>/mis-predicciones/', views.mis_predicciones, name='mis_predicciones'),
    path('torneo/<int:tournament_id>/mis-predicciones/grupo/<str:group_letter>/', views.save_group_prediction, name='save_group_prediction'),
    path('torneo/<int:tournament_id>/mis-predicciones/terceros/', views.save_terceros, name='save_terceros'),
    path('torneo/<int:tournament_id>/ranking/', views.ranking, name='ranking'),
    path('torneo/<int:tournament_id>/predicciones-especiales/', views.predicciones_especiales, name='predicciones_especiales'),
    path('', views.home, name='home'),
]
