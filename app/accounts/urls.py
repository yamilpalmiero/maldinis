from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('registro/', views.registro, name='registro'),
    path('reglamento/', views.reglamento, name='reglamento'),
    path('reglas-vistas/', views.marcar_reglas_vistas, name='marcar_reglas_vistas'),
]