from django.urls import path
from . import views

urlpatterns = [
    path('', views.mis_torneos, name='mis_torneos'),
    path('crear/', views.crear_torneo, name='crear_torneo'),
    path('unirse/', views.unirse_torneo, name='unirse_torneo'),
]