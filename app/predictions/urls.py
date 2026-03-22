from django.urls import path
from . import views

urlpatterns = [
    path('torneo/<int:tournament_id>/fixture/', views.fixture, name='fixture'),
    path('torneo/<int:tournament_id>/mis-predicciones/', views.mis_predicciones, name='mis_predicciones'),
    path('torneo/<int:tournament_id>/ranking/', views.ranking, name='ranking'),
    path('torneo/<int:tournament_id>/predicciones-especiales/', views.predicciones_especiales, name='predicciones_especiales'),
    path('', views.home, name='home'),
]