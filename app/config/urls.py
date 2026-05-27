from django.contrib import admin
from django.urls import path, include
from django.views.generic.base import RedirectView
from django.contrib.staticfiles.storage import staticfiles_storage

from predictions.api import sync_world_cup_view


urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('torneos/', include('tournaments.urls')),
    path('api/sync/world-cup/', sync_world_cup_view, name='api_sync_world_cup'),
    path('', include('predictions.urls')),
    path('favicon.ico', RedirectView.as_view(url=staticfiles_storage.url('favicon.svg'))),
]