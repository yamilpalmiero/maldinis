from django.contrib import admin
from django.urls import path, include
from django.views.generic.base import RedirectView
from django.contrib.staticfiles.storage import staticfiles_storage



urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('torneos/', include('tournaments.urls')),
    path('', include('predictions.urls')),
    path('favicon.ico', RedirectView.as_view(url=staticfiles_storage.url('favicon.svg'))),

]