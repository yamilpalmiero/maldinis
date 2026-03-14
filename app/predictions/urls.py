from django.urls import path
from . import views

urlpatterns = [
    path('fixture/', views.fixture, name='fixture'),
    path('mis-predicciones/', views.mis_predicciones, name='mis_predicciones'),
    path('ranking/', views.ranking, name='ranking'),
    path('', views.home, name='home'),
]